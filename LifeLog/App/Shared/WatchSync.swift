import Foundation
import Observation
import LifeLogKit
#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

/// Keeps iPhone and Watch stores in step over WatchConnectivity.
///
/// Every local change is marked pending in the store and sent with
/// `transferUserInfo`, which the system queues and delivers even if the other
/// device is out of range or the app isn't running. Pending flags are cleared
/// only when the system reports the transfer finished, and merges are
/// last-writer-wins, so re-sending is always safe.
@MainActor
@Observable
final class WatchSync: NSObject {
    static let shared = WatchSync()

    private(set) var isSupported = false
    private(set) var isPaired = false
    private(set) var isCounterpartInstalled = false
    private(set) var isReachable = false
    private(set) var lastSentAt: Date?
    private(set) var lastReceivedAt: Date?
    private(set) var lastError: String?

    @ObservationIgnored private var store: Store { StoreFactory.shared }
    @ObservationIgnored private var pushTask: Task<Void, Never>?
    @ObservationIgnored private var inFlight = Set<RecordStamp>()

    var pendingCount: Int { store.pendingChanges(maxEntries: 10_000).entries.count }

    #if canImport(WatchConnectivity)
    private var session: WCSession? { WCSession.isSupported() ? WCSession.default : nil }
    #endif

    func activate() {
        #if canImport(WatchConnectivity)
        guard let session else { return }
        isSupported = true
        session.delegate = self
        session.activate()
        #endif
    }

    /// Debounced push of pending changes.
    func schedulePush() {
        pushTask?.cancel()
        pushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            guard !Task.isCancelled else { return }
            self?.pushPending()
        }
    }

    private var canSend: Bool {
        #if canImport(WatchConnectivity)
        guard let session, session.activationState == .activated else { return false }
        #if os(iOS)
        return session.isPaired && session.isWatchAppInstalled
        #else
        return true
        #endif
        #else
        return false
        #endif
    }

    func pushPending() {
        #if canImport(WatchConnectivity)
        guard canSend, let session else { return }
        var batch = store.pendingChanges(maxEntries: 400)
        batch.entries.removeAll { inFlight.contains(RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt)) }
        batch.measures.removeAll { inFlight.contains(RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt)) }
        batch.sessions.removeAll { inFlight.contains(RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt)) }
        guard !batch.isEmpty else { return }
        #if os(iOS)
        // The Watch only needs recent history; older entries stay on the iPhone.
        let cutoff = Date().addingTimeInterval(-14 * 86_400)
        let old = batch.entries.filter { $0.occurredAt < cutoff }
        if !old.isEmpty {
            try? store.markSynced(SyncReceipt(entries: old.map { RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt) }))
            batch.entries.removeAll { $0.occurredAt < cutoff }
            if batch.isEmpty { return }
        }
        #endif
        for chunk in batch.chunked(maxEntries: 100) {
            send(chunk, via: session)
        }
        lastSentAt = Date()
        #endif
    }

    /// Sends everything again (the other side ignores what it already has).
    func resyncEverything() {
        try? store.markAllPending()
        inFlight.removeAll()
        pushPending()
        #if canImport(WatchConnectivity)
        if let session, session.activationState == .activated {
            session.transferUserInfo(["kind": "requestAll"])
        }
        #endif
    }

    #if canImport(WatchConnectivity)
    private func send(_ batch: SyncBatch, via session: WCSession) {
        guard let data = try? batch.encoded() else { return }
        for e in batch.entries { inFlight.insert(RecordStamp(id: e.id, modifiedAt: e.modifiedAt)) }
        for m in batch.measures { inFlight.insert(RecordStamp(id: m.id, modifiedAt: m.modifiedAt)) }
        for s in batch.sessions { inFlight.insert(RecordStamp(id: s.id, modifiedAt: s.modifiedAt)) }
        session.transferUserInfo(["kind": "batch", "v": SyncBatch.formatVersion, "payload": data])
    }

    private func refreshState(_ session: WCSession) {
        isReachable = session.isReachable
        #if os(iOS)
        isPaired = session.isPaired
        isCounterpartInstalled = session.isWatchAppInstalled
        #else
        isPaired = true
        isCounterpartInstalled = session.isCompanionAppInstalled
        #endif
    }

    fileprivate func handle(userInfo: [String: Any]) {
        switch userInfo["kind"] as? String {
        case "batch":
            guard let data = userInfo["payload"] as? Data else { return }
            do {
                let batch = try SyncBatch.decode(data)
                try store.apply(batch)
                lastReceivedAt = Date()
            } catch {
                lastError = "Couldn’t read data from the other device: \(error)"
            }
        case "requestAll":
            try? store.markAllPending()
            inFlight.removeAll()
            pushPending()
        default:
            break
        }
    }

    fileprivate func finished(_ userInfo: [String: Any], error: Error?) {
        guard userInfo["kind"] as? String == "batch", let data = userInfo["payload"] as? Data,
              let batch = try? SyncBatch.decode(data) else { return }
        let receipt = batch.receipt
        for s in receipt.entries + receipt.measures + receipt.sessions { inFlight.remove(s) }
        if let error {
            lastError = error.localizedDescription
            schedulePush()
        } else {
            try? store.markSynced(receipt)
            lastError = nil
        }
    }
    #endif
}

#if canImport(WatchConnectivity)
extension WatchSync: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
                             error: Error?) {
        Task { @MainActor in
            self.refreshState(session)
            if let error { self.lastError = error.localizedDescription }
            #if os(watchOS)
            // First launch on a Watch: ask the iPhone for its measures and settings.
            if !StoreFactory.defaults.bool(forKey: "LifeLogRequestedInitialSync") {
                session.transferUserInfo(["kind": "requestAll"])
                StoreFactory.defaults.set(true, forKey: "LifeLogRequestedInitialSync")
            }
            #endif
            self.pushPending()
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        let info = userInfo
        Task { @MainActor in self.handle(userInfo: info) }
    }

    nonisolated func session(_ session: WCSession, didFinish userInfoTransfer: WCSessionUserInfoTransfer, error: Error?) {
        let info = userInfoTransfer.userInfo
        Task { @MainActor in self.finished(info, error: error) }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in
            self.refreshState(session)
            if session.isReachable { self.pushPending() }
        }
    }

    #if os(iOS)
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}

    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        // The user switched watches: reactivate for the new one and send it everything.
        session.activate()
        Task { @MainActor in self.resyncEverything() }
    }

    nonisolated func sessionWatchStateDidChange(_ session: WCSession) {
        Task { @MainActor in
            let wasInstalled = self.isCounterpartInstalled
            self.refreshState(session)
            if session.isWatchAppInstalled && !wasInstalled { self.resyncEverything() } else { self.pushPending() }
        }
    }
    #else
    nonisolated func sessionCompanionAppInstalledDidChange(_ session: WCSession) {
        Task { @MainActor in self.refreshState(session) }
    }
    #endif
}
#endif
