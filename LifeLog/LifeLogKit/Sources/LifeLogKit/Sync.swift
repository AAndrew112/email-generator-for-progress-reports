import Foundation

/// Identifies one version of a record.
public struct RecordStamp: Codable, Hashable, Sendable {
    public var id: UUID
    public var modifiedAt: Date
    public init(id: UUID, modifiedAt: Date) {
        self.id = id
        self.modifiedAt = modifiedAt
    }
}

/// What a sender can mark as delivered once a batch has been transferred.
public struct SyncReceipt: Codable, Hashable, Sendable {
    public var measures: [RecordStamp]
    public var entries: [RecordStamp]
    public var sessions: [RecordStamp]
    public var settingsModifiedAt: Date?

    public init(measures: [RecordStamp] = [], entries: [RecordStamp] = [], sessions: [RecordStamp] = [],
                settingsModifiedAt: Date? = nil) {
        self.measures = measures
        self.entries = entries
        self.sessions = sessions
        self.settingsModifiedAt = settingsModifiedAt
    }
}

/// A set of records exchanged between iPhone and Watch (or restored from a backup).
public struct SyncBatch: Codable, Sendable {
    public static let formatVersion = 1

    public var formatVersion: Int
    public var senderDeviceID: String
    public var sentAt: Date
    public var measures: [Measure]
    public var entries: [Entry]
    public var sessions: [CheckInSession]
    public var settings: AppSettings?
    public var isFullSnapshot: Bool

    public init(senderDeviceID: String, sentAt: Date, measures: [Measure] = [], entries: [Entry] = [],
                sessions: [CheckInSession] = [], settings: AppSettings? = nil, isFullSnapshot: Bool = false) {
        self.formatVersion = SyncBatch.formatVersion
        self.senderDeviceID = senderDeviceID
        self.sentAt = sentAt
        self.measures = measures
        self.entries = entries
        self.sessions = sessions
        self.settings = settings
        self.isFullSnapshot = isFullSnapshot
    }

    public var isEmpty: Bool { measures.isEmpty && entries.isEmpty && sessions.isEmpty && settings == nil }

    public var receipt: SyncReceipt {
        SyncReceipt(measures: measures.map { RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt) },
                    entries: entries.map { RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt) },
                    sessions: sessions.map { RecordStamp(id: $0.id, modifiedAt: $0.modifiedAt) },
                    settingsModifiedAt: settings?.modifiedAt)
    }

    /// Splits a large batch so each transfer stays small. Measures and settings
    /// travel in the first chunk so entries never arrive before their definitions.
    public func chunked(maxEntries: Int = 150) -> [SyncBatch] {
        guard entries.count > maxEntries else { return [self] }
        var chunks: [SyncBatch] = []
        var start = 0
        while start < entries.count {
            let end = min(start + maxEntries, entries.count)
            var b = SyncBatch(senderDeviceID: senderDeviceID, sentAt: sentAt, entries: Array(entries[start..<end]),
                              isFullSnapshot: isFullSnapshot)
            if start == 0 {
                b.measures = measures
                b.sessions = sessions
                b.settings = settings
            }
            chunks.append(b)
            start = end
        }
        return chunks
    }

    private static func coder() -> (JSONEncoder, JSONDecoder) {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .deferredToDate
        let d = JSONDecoder()
        d.dateDecodingStrategy = .deferredToDate
        return (e, d)
    }

    public func encoded() throws -> Data { try SyncBatch.coder().0.encode(self) }

    public static func decode(_ data: Data) throws -> SyncBatch { try coder().1.decode(SyncBatch.self, from: data) }
}

public struct SyncApplyResult: Equatable, Sendable {
    public var inserted = 0
    public var updated = 0
    public var ignored = 0
    public var settingsUpdated = false
    public init() {}
    public var changedAnything: Bool { inserted > 0 || updated > 0 || settingsUpdated }
}

public enum Conflict {
    /// Last writer wins; ties are broken deterministically by device ID so both
    /// devices converge on the same version.
    public static func remoteWins(local: (Date, String), remote: (Date, String)) -> Bool {
        let delta = remote.0.timeIntervalSince(local.0)
        if abs(delta) < 0.0005 { return remote.1 > local.1 }
        return delta > 0
    }
}
