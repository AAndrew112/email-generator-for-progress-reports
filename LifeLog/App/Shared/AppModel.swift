import Foundation
import Observation
import LifeLogKit
#if canImport(WidgetKit)
import WidgetKit
#endif

/// Transient confirmation shown after logging, with Undo.
struct LogToast: Identifiable, Equatable {
    let id = UUID()
    let entryID: UUID
    let title: String
    let detail: String
}

/// UI-facing state for both the iPhone and Watch apps. Thin layer over `Store`.
@MainActor
@Observable
final class AppModel {
    let store: Store
    private(set) var measures: [Measure] = []
    private(set) var settings = AppSettings()
    private(set) var todayKey = ""
    private(set) var todayEntries: [Entry] = []
    private(set) var todaySessions: [CheckInSession] = []
    /// Bumped on every reload so views can refresh derived data.
    private(set) var revision = 0
    var toast: LogToast?
    var errorMessage: String?

    @ObservationIgnored private var observer: NSObjectProtocol?
    @ObservationIgnored private var toastTask: Task<Void, Never>?
    @ObservationIgnored var onLocalChange: (() -> Void)?

    init(store: Store) {
        self.store = store
        errorMessage = StoreFactory.openError
        reload()
        observer = NotificationCenter.default.addObserver(forName: Store.didChangeNotification, object: store,
                                                          queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.reload() }
        }
    }

    func reload() {
        settings = store.settings()
        measures = store.measures()
        todayKey = store.dayKey(for: Date())
        todayEntries = store.entries(dayKey: todayKey)
        todaySessions = store.sessions(dayKey: todayKey)
        revision += 1
    }

    // MARK: Lookups

    var activeMeasures: [Measure] { measures.filter(\.isActive) }
    var favorites: [QuickAction] { QuickLogger.favorites(from: measures) }
    var quickActions: [QuickAction] { QuickLogger.allActions(from: measures) }

    func measure(_ id: UUID) -> Measure? { measures.first { $0.id == id } ?? store.measure(id: id) }

    func checkInMeasures(_ kind: CheckInKind) -> [Measure] {
        activeMeasures.filter { $0.isIn(kind) }
    }

    func completedSession(_ kind: CheckInKind) -> CheckInSession? {
        todaySessions.last { $0.kind == kind && $0.completedAt != nil }
    }

    /// The check-in to suggest right now.
    var suggestedCheckIn: CheckInKind {
        let hour = Calendar.current.component(.hour, from: Date())
        if completedSession(.morning) == nil && hour < settings.eveningStartsHour && hour >= settings.dayBoundaryHour {
            return .morning
        }
        return hour >= 12 ? .evening : .morning
    }

    /// Today's entry for a once-per-day measure, if one exists.
    func todayEntry(for measure: Measure) -> Entry? {
        todayEntries.last { $0.measureID == measure.id }
    }

    func entry(for measure: Measure, dayKey: String) -> Entry? {
        dayKey == todayKey ? todayEntry(for: measure) : store.entries(dayKey: dayKey).last { $0.measureID == measure.id }
    }

    func count(_ action: QuickAction) -> Int { QuickLogger.count(of: action, in: todayEntries) }

    var studyStatus: (Study, Int)? { settings.study(containing: todayKey) }

    // MARK: Logging

    enum QuickOutcome {
        case logged(Entry)
        case needsInput(QuickAction, existing: Entry?)
    }

    /// One-tap logging. Returns `.needsInput` when required values are missing
    /// (or a once-per-day measure already has today's entry).
    func quickLog(_ action: QuickAction, context: EntryContext = .quickLog) -> QuickOutcome {
        do {
            if let e = try QuickLogger.logIfComplete(action, store: store, context: context) {
                didLog(e, measure: action.measure, title: action.title)
                return .logged(e)
            }
        } catch {
            errorMessage = "Couldn’t save: \(error)"
        }
        let existing = action.measure.cardinality == .oncePerDay ? todayEntry(for: action.measure) : nil
        return .needsInput(action, existing: existing)
    }

    /// Saves a new or edited entry.
    @discardableResult
    func save(_ entry: Entry, announce: Bool = false) -> Entry? {
        do {
            let saved = try store.saveEntry(entry)
            if announce, let m = measure(saved.measureID) { didLog(saved, measure: m, title: m.name) } else { localChange() }
            return saved
        } catch {
            errorMessage = "Couldn’t save: \(error)"
            return nil
        }
    }

    func delete(_ entryID: UUID) {
        do { try store.deleteEntry(id: entryID); localChange() } catch { errorMessage = "Couldn’t delete: \(error)" }
    }

    func restore(_ entryID: UUID) {
        do { try store.restoreEntry(id: entryID); localChange() } catch { errorMessage = "Couldn’t restore: \(error)" }
    }

    func undo(_ toast: LogToast) {
        delete(toast.entryID)
        self.toast = nil
    }

    private func didLog(_ entry: Entry, measure: Measure, title: String) {
        let detail = ValueText.summary(of: entry, measure: measure)
        let t = LogToast(entryID: entry.id, title: title, detail: detail)
        toast = t
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            guard !Task.isCancelled else { return }
            if self?.toast == t { self?.toast = nil }
        }
        localChange()
    }

    private func localChange() {
        onLocalChange?()
        #if canImport(WidgetKit) && os(iOS)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
    }

    // MARK: Check-ins

    func startSession(_ kind: CheckInKind, measures: [Measure]) -> CheckInSession {
        let existing = todaySessions.last { $0.kind == kind && $0.completedAt == nil }
        if let existing { return existing }
        let s = CheckInSession(kind: kind, dayKey: todayKey, startedAt: Date(), timeZone: .current,
                               presentedMeasureKeys: measures.map(\.key), source: store.defaultSource)
        return (try? store.saveSession(s)) ?? s
    }

    @discardableResult
    func saveSession(_ s: CheckInSession) -> CheckInSession {
        do {
            let saved = try store.saveSession(s)
            localChange()
            return saved
        } catch {
            errorMessage = "Couldn’t save check-in: \(error)"
            return s
        }
    }

    // MARK: Measures & settings

    func existingKeys() -> [String: UUID] {
        Dictionary(store.measures(includeDeleted: true).map { ($0.key, $0.id) }, uniquingKeysWith: { a, _ in a })
    }

    @discardableResult
    func saveMeasure(_ m: Measure) -> Measure? {
        do {
            let saved = try store.saveMeasure(m)
            localChange()
            return saved
        } catch {
            errorMessage = "Couldn’t save measure: \(error)"
            return nil
        }
    }

    func reorder(_ ids: [UUID]) {
        do { try store.reorderMeasures(ids); localChange() } catch { errorMessage = "\(error)" }
    }

    func deleteMeasure(_ id: UUID) {
        do { try store.deleteMeasure(id: id); localChange() } catch { errorMessage = "\(error)" }
    }

    func saveSettings(_ s: AppSettings) {
        do { try store.saveSettings(s); localChange() } catch { errorMessage = "Couldn’t save settings: \(error)" }
    }

    var groups: [String] {
        var seen: [String] = []
        for m in measures where !seen.contains(m.group) { seen.append(m.group) }
        for g in ["Sleep", "Mind", "Screen", "Intake", "Skin", "Custom"] where !seen.contains(g) { seen.append(g) }
        return seen
    }
}
