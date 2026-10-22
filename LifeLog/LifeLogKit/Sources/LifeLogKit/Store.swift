import Foundation

/// The local database. Every record is stored as JSON alongside a few indexed
/// columns, every save of an entry or measure appends a revision snapshot, and
/// deletions are soft (tombstones) so history and sync stay intact.
///
/// All access is serialised on a private queue, so a `Store` can be shared freely.
public final class Store: @unchecked Sendable {
    public static let didChangeNotification = Notification.Name("LifeLogStoreDidChange")
    public static let schemaVersion = 1

    public let deviceID: String
    /// Default `EntrySource` for entries created on this device.
    public let defaultSource: EntrySource
    /// Injectable clock (tests).
    public var now: () -> Date = { Date() }

    private let db: SQLiteDatabase
    private let queue = DispatchQueue(label: "lifelog.store")
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    /// Non-fatal problems (e.g. a row that failed to decode). Surfaced in Settings.
    public private(set) var lastError: String?

    /// - Parameter url: database file location, or nil for an in-memory database.
    public init(url: URL?, deviceID: String, defaultSource: EntrySource = .iPhone) throws {
        self.deviceID = deviceID
        self.defaultSource = defaultSource
        if let url {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            db = try SQLiteDatabase(path: url.path)
        } else {
            db = try SQLiteDatabase(path: ":memory:")
        }
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .deferredToDate
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .deferredToDate
        try migrate()
    }

    public static func inMemory(deviceID: String = "test-device", source: EntrySource = .iPhone) throws -> Store {
        try Store(url: nil, deviceID: deviceID, defaultSource: source)
    }

    // MARK: - Schema

    private func migrate() throws {
        if db.userVersion < 1 {
            try db.transaction {
                try db.execute("""
                CREATE TABLE IF NOT EXISTS measures (
                    id TEXT PRIMARY KEY, key TEXT NOT NULL, sort_order INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0, modified_at REAL NOT NULL,
                    pending INTEGER NOT NULL DEFAULT 0, json BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS measure_revisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, measure_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    changed_at REAL NOT NULL, device_id TEXT NOT NULL, json BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_measure_revisions ON measure_revisions(measure_id);
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, measure_id TEXT NOT NULL, occurred_at REAL NOT NULL,
                    day_key TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, modified_at REAL NOT NULL,
                    pending INTEGER NOT NULL DEFAULT 0, json BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_entries_day ON entries(day_key);
                CREATE INDEX IF NOT EXISTS idx_entries_measure ON entries(measure_id, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_entries_occurred ON entries(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_entries_pending ON entries(pending);
                CREATE TABLE IF NOT EXISTS entry_revisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    change_kind TEXT NOT NULL, changed_at REAL NOT NULL, device_id TEXT NOT NULL, json BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_entry_revisions ON entry_revisions(entry_id);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, day_key TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0, modified_at REAL NOT NULL,
                    pending INTEGER NOT NULL DEFAULT 0, json BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_sessions_day ON sessions(day_key);
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                """)
                try db.setUserVersion(1)
            }
        }
    }

    // MARK: - Helpers

    private func notifyChange() {
        NotificationCenter.default.post(name: Store.didChangeNotification, object: self)
    }

    private func encode<T: Encodable>(_ value: T) throws -> Data { try encoder.encode(value) }

    private func decodeRows<T: Decodable>(_ type: T.Type, sql: String, _ params: [SQLiteDatabase.Value] = []) -> [T] {
        do {
            let blobs = try db.query(sql, params) { $0.blob(0) ?? Data() }
            var out: [T] = []
            out.reserveCapacity(blobs.count)
            for b in blobs {
                do { out.append(try decoder.decode(T.self, from: b)) } catch { lastError = "Skipped unreadable record: \(error)" }
            }
            return out
        } catch {
            lastError = "\(error)"
            return []
        }
    }

    private func kvGet(_ key: String) -> Data? {
        (try? db.query("SELECT value FROM kv WHERE key = ?", [.text(key)]) { $0.blob(0) })?.first ?? nil
    }

    private func kvSet(_ key: String, _ value: Data) throws {
        try db.run("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   [.text(key), .blob(value)])
    }

    /// A timestamp strictly after `previous`, so a local edit always beats the version it replaces.
    private func stamp(after previous: Date?) -> Date {
        let t = now()
        guard let previous, t <= previous else { return t }
        return previous.addingTimeInterval(0.001)
    }

    // MARK: - Settings

    private var cachedSettings: AppSettings?

    public func settings() -> AppSettings {
        queue.sync { _settings() }
    }

    private func _settings() -> AppSettings {
        if let s = cachedSettings { return s }
        let s = kvGet("settings").flatMap { try? decoder.decode(AppSettings.self, from: $0) } ?? AppSettings()
        cachedSettings = s
        return s
    }

    public func saveSettings(_ newValue: AppSettings) throws {
        try queue.sync {
            let old = _settings()
            var s = newValue
            s.modifiedAt = stamp(after: old.modifiedAt)
            s.modifiedBy = deviceID
            try db.transaction {
                try kvSet("settings", try encode(s))
                try kvSet("settings_pending", Data([1]))
                if old.dayBoundaryHour != s.dayBoundaryHour { try _recomputeDayKeys(boundary: s.dayBoundaryHour) }
            }
            cachedSettings = s
        }
        notifyChange()
    }

    public func dayKey(for date: Date, timeZone: TimeZone = .current) -> String {
        DayKey.make(for: date, timeZone: timeZone, boundaryHour: settings().dayBoundaryHour)
    }

    /// Day boundary changed: logical days are derived data, so recompute without new revisions.
    private func _recomputeDayKeys(boundary: Int) throws {
        let entries: [Entry] = decodeRows(Entry.self, sql: "SELECT json FROM entries")
        for var e in entries {
            let key = DayKey.make(for: e.occurredAt, timeZone: e.timeZone, boundaryHour: boundary)
            guard key != e.dayKey else { continue }
            e.dayKey = key
            try db.run("UPDATE entries SET day_key = ?, json = ? WHERE id = ?",
                       [.text(key), .blob(try encode(e)), .text(e.id.uuidString)])
        }
        let sessions: [CheckInSession] = decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions")
        for var s in sessions {
            let key = DayKey.make(for: s.startedAt, timeZone: s.timeZone, boundaryHour: boundary)
            guard key != s.dayKey else { continue }
            s.dayKey = key
            try db.run("UPDATE sessions SET day_key = ?, json = ? WHERE id = ?",
                       [.text(key), .blob(try encode(s)), .text(s.id.uuidString)])
        }
    }

    // MARK: - Measures

    /// Inserts the built-in measures the first time the store is opened.
    public func seedIfNeeded() throws {
        var changed = false
        try queue.sync {
            guard kvGet("seeded") == nil else { return }
            try db.transaction {
                for m in Seed.measures() {
                    if try _measure(m.id) != nil { continue }
                    try _writeMeasure(m, pending: false)
                    try _logMeasureRevision(m)
                }
                var s = _settings()
                if s.studies.isEmpty {
                    s.studies = [AppSettings.scrollingStudy]
                    try kvSet("settings", try encode(s))
                    cachedSettings = s
                }
                try kvSet("seeded", Data([1]))
            }
            changed = true
        }
        if changed { notifyChange() }
    }

    public func measures(includeDeleted: Bool = false) -> [Measure] {
        queue.sync {
            decodeRows(Measure.self, sql: includeDeleted
                       ? "SELECT json FROM measures ORDER BY sort_order, key"
                       : "SELECT json FROM measures WHERE deleted = 0 ORDER BY sort_order, key")
        }
    }

    public func measure(id: UUID) -> Measure? {
        queue.sync { try? _measure(id) }
    }

    private func _measure(_ id: UUID) throws -> Measure? {
        decodeRows(Measure.self, sql: "SELECT json FROM measures WHERE id = ?", [.text(id.uuidString)]).first
    }

    private func _writeMeasure(_ m: Measure, pending: Bool) throws {
        try db.run("""
            INSERT INTO measures(id, key, sort_order, deleted, modified_at, pending, json) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET key = excluded.key, sort_order = excluded.sort_order,
              deleted = excluded.deleted, modified_at = excluded.modified_at, pending = excluded.pending,
              json = excluded.json
            """, [.text(m.id.uuidString), .text(m.key), .int(Int64(m.sortOrder)), .int(m.deletedAt == nil ? 0 : 1),
                  .double(m.modifiedAt.timeIntervalSinceReferenceDate), .int(pending ? 1 : 0), .blob(try encode(m))])
    }

    private func _logMeasureRevision(_ m: Measure) throws {
        try db.run("INSERT INTO measure_revisions(measure_id, revision, changed_at, device_id, json) VALUES(?,?,?,?,?)",
                   [.text(m.id.uuidString), .int(Int64(m.revision)), .double(m.modifiedAt.timeIntervalSinceReferenceDate),
                    .text(m.modifiedBy), .blob(try encode(m))])
    }

    /// Saves a new or edited measure.
    ///
    /// Guarantees that keep exports interpretable: measure and field keys never
    /// change once created, and fields or options removed in the editor are kept
    /// as archived definitions rather than deleted.
    @discardableResult
    public func saveMeasure(_ input: Measure) throws -> Measure {
        let result: Measure = try queue.sync {
            var m = input
            let existing = try _measure(m.id)
            if let old = existing {
                m.key = old.key
                m.createdAt = old.createdAt
                for (i, f) in m.fields.enumerated() {
                    guard let oldField = old.fields.first(where: { $0.id == f.id }) else { continue }
                    m.fields[i].key = oldField.key
                    for oldOption in oldField.options where !f.options.contains(where: { $0.key == oldOption.key }) {
                        var archived = oldOption
                        archived.isArchived = true
                        m.fields[i].options.append(archived)
                    }
                }
                for oldField in old.fields where !m.fields.contains(where: { $0.id == oldField.id }) {
                    var archived = oldField
                    archived.isArchived = true
                    m.fields.append(archived)
                }
                // Nothing changed: avoid a meaningless revision.
                var probe = m
                probe.modifiedAt = old.modifiedAt
                probe.revision = old.revision
                probe.modifiedBy = old.modifiedBy
                if probe == old { return old }
            } else {
                let taken = Set(try db.query("SELECT key FROM measures") { $0.text(0) ?? "" })
                m.key = Slug.unique(Slug.make(m.key.isEmpty ? m.name : m.key), existing: taken)
                m.createdAt = now()
            }
            m.revision = (existing?.revision ?? 0) + 1
            m.modifiedAt = stamp(after: existing?.modifiedAt)
            m.modifiedBy = deviceID
            try db.transaction {
                try _writeMeasure(m, pending: true)
                try _logMeasureRevision(m)
            }
            return m
        }
        notifyChange()
        return result
    }

    /// Persists a new ordering (sort orders are 0, 10, 20, ...).
    public func reorderMeasures(_ ids: [UUID]) throws {
        for (i, id) in ids.enumerated() {
            guard var m = measure(id: id), m.sortOrder != i * 10 else { continue }
            m.sortOrder = i * 10
            try saveMeasure(m)
        }
    }

    /// Soft-deletes a measure. Its entries and definition history are kept.
    public func deleteMeasure(id: UUID) throws {
        guard var m = measure(id: id) else { return }
        m.deletedAt = now()
        m.isActive = false
        try saveMeasure(m)
    }

    public func measureRevisions(measureID: UUID? = nil) -> [MeasureRevision] {
        queue.sync {
            let rows: [(UUID, Int, Double, String, Data)]
            do {
                let sql = "SELECT measure_id, revision, changed_at, device_id, json FROM measure_revisions"
                    + (measureID == nil ? "" : " WHERE measure_id = ?") + " ORDER BY seq"
                rows = try db.query(sql, measureID.map { [.text($0.uuidString)] } ?? []) {
                    (UUID(uuidString: $0.text(0) ?? "") ?? UUID(), Int($0.int(1)), $0.double(2), $0.text(3) ?? "", $0.blob(4) ?? Data())
                }
            } catch { return [] }
            return rows.compactMap { r in
                guard let snap = try? decoder.decode(Measure.self, from: r.4) else { return nil }
                return MeasureRevision(measureID: r.0, revision: r.1, changedAt: Date(timeIntervalSinceReferenceDate: r.2),
                                       deviceID: r.3, snapshot: snap)
            }
        }
    }

    // MARK: - Entries

    /// Builds (but does not save) a new entry for `measure`.
    public func makeEntry(for measure: Measure, values: [String: FieldValue]? = nil, occurredAt: Date? = nil,
                          context: EntryContext = .quickLog, source: EntrySource? = nil,
                          sessionID: UUID? = nil, presetID: UUID? = nil, note: String? = nil) -> Entry {
        let t = now()
        let at = occurredAt ?? t
        return Entry(measureID: measure.id, measureKey: measure.key, measureRevision: measure.revision,
                     occurredAt: at, timeZone: .current, dayKey: dayKey(for: at),
                     values: values ?? measure.defaultValues, note: note, context: context,
                     source: source ?? defaultSource, sessionID: sessionID, presetID: presetID,
                     createdAt: t, modifiedAt: t, originDevice: deviceID, modifiedBy: deviceID)
    }

    public func entry(id: UUID) -> Entry? { queue.sync { try? _entry(id) } }

    private func _entry(_ id: UUID) throws -> Entry? {
        decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE id = ?", [.text(id.uuidString)]).first
    }

    private func _writeEntry(_ e: Entry, pending: Bool) throws {
        try db.run("""
            INSERT INTO entries(id, measure_id, occurred_at, day_key, deleted, modified_at, pending, json)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET measure_id = excluded.measure_id, occurred_at = excluded.occurred_at,
              day_key = excluded.day_key, deleted = excluded.deleted, modified_at = excluded.modified_at,
              pending = excluded.pending, json = excluded.json
            """, [.text(e.id.uuidString), .text(e.measureID.uuidString), .double(e.occurredAt.timeIntervalSinceReferenceDate),
                  .text(e.dayKey), .int(e.deletedAt == nil ? 0 : 1), .double(e.modifiedAt.timeIntervalSinceReferenceDate),
                  .int(pending ? 1 : 0), .blob(try encode(e))])
    }

    private func _logEntryRevision(_ e: Entry, kind: ChangeKind) throws {
        try db.run("""
            INSERT INTO entry_revisions(entry_id, revision, change_kind, changed_at, device_id, json) VALUES(?,?,?,?,?,?)
            """, [.text(e.id.uuidString), .int(Int64(e.revision)), .text(kind.rawValue),
                  .double(now().timeIntervalSinceReferenceDate), .text(e.modifiedBy), .blob(try encode(e))])
    }

    /// Saves a new or edited entry: bumps its revision, stamps it, recomputes its
    /// logical day and appends a snapshot to the edit history.
    @discardableResult
    public func saveEntry(_ input: Entry) throws -> Entry {
        let saved = try queue.sync { try _saveEntry(input, kind: nil) }
        notifyChange()
        return saved
    }

    private func _saveEntry(_ input: Entry, kind: ChangeKind?) throws -> Entry {
        var e = input
        e.values = e.values.filter { !$0.value.isEmpty }
        if let n = e.note, n.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { e.note = nil }
        let existing = try _entry(e.id)
        if kind == nil, let existing, existing.hasSameContent(as: e) { return existing }
        e.revision = (existing?.revision ?? 0) + 1
        if let existing {
            e.createdAt = existing.createdAt
            e.originDevice = existing.originDevice
        } else if e.originDevice.isEmpty {
            e.originDevice = deviceID
        }
        e.modifiedAt = stamp(after: existing?.modifiedAt)
        e.modifiedBy = deviceID
        e.utcOffsetSeconds = e.timeZone.secondsFromGMT(for: e.occurredAt)
        e.dayKey = DayKey.make(for: e.occurredAt, timeZone: e.timeZone, boundaryHour: _settings().dayBoundaryHour)
        if let m = try _measure(e.measureID) {
            e.measureKey = m.key
            e.measureRevision = m.revision
        }
        let changeKind: ChangeKind = kind ?? (existing == nil ? .created : .updated)
        try db.transaction {
            try _writeEntry(e, pending: true)
            try _logEntryRevision(e, kind: changeKind)
        }
        return e
    }

    /// Soft-deletes an entry (kept in history; can be restored).
    public func deleteEntry(id: UUID) throws {
        try queue.sync {
            guard var e = try _entry(id), e.deletedAt == nil else { return }
            e.deletedAt = now()
            _ = try _saveEntry(e, kind: .deleted)
        }
        notifyChange()
    }

    public func restoreEntry(id: UUID) throws {
        try queue.sync {
            guard var e = try _entry(id), e.deletedAt != nil else { return }
            e.deletedAt = nil
            _ = try _saveEntry(e, kind: .restored)
        }
        notifyChange()
    }

    public func entries(dayKey: String, includeDeleted: Bool = false) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE day_key = ?"
                       + (includeDeleted ? "" : " AND deleted = 0") + " ORDER BY occurred_at", [.text(dayKey)])
        }
    }

    public func entries(from start: Date, to end: Date, includeDeleted: Bool = false) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE occurred_at >= ? AND occurred_at < ?"
                       + (includeDeleted ? "" : " AND deleted = 0") + " ORDER BY occurred_at",
                       [.double(start.timeIntervalSinceReferenceDate), .double(end.timeIntervalSinceReferenceDate)])
        }
    }

    public func entries(measureID: UUID, limit: Int = 500) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE measure_id = ? AND deleted = 0 ORDER BY occurred_at DESC LIMIT ?",
                       [.text(measureID.uuidString), .int(Int64(limit))])
        }
    }

    /// Most recent entries first.
    public func recentEntries(limit: Int = 200, offset: Int = 0) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE deleted = 0 ORDER BY occurred_at DESC LIMIT ? OFFSET ?",
                       [.int(Int64(limit)), .int(Int64(offset))])
        }
    }

    public func deletedEntries(limit: Int = 200) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE deleted = 1 ORDER BY modified_at DESC LIMIT ?",
                       [.int(Int64(limit))])
        }
    }

    public func allEntries(includeDeleted: Bool = false) -> [Entry] {
        queue.sync {
            decodeRows(Entry.self, sql: "SELECT json FROM entries" + (includeDeleted ? "" : " WHERE deleted = 0")
                       + " ORDER BY occurred_at")
        }
    }

    public func entryCount() -> Int {
        queue.sync { (try? db.query("SELECT COUNT(*) FROM entries WHERE deleted = 0") { Int($0.int(0)) }.first) ?? 0 }
    }

    public func entryRevisions(entryID: UUID? = nil) -> [EntryRevision] {
        queue.sync {
            let sql = "SELECT entry_id, revision, change_kind, changed_at, device_id, json FROM entry_revisions"
                + (entryID == nil ? "" : " WHERE entry_id = ?") + " ORDER BY seq"
            let rows = (try? db.query(sql, entryID.map { [.text($0.uuidString)] } ?? []) {
                ($0.text(0) ?? "", Int($0.int(1)), $0.text(2) ?? "", $0.double(3), $0.text(4) ?? "", $0.blob(5) ?? Data())
            }) ?? []
            return rows.compactMap { r in
                guard let id = UUID(uuidString: r.0), let snap = try? decoder.decode(Entry.self, from: r.5) else { return nil }
                return EntryRevision(entryID: id, revision: r.1, changeKind: ChangeKind(rawValue: r.2) ?? .updated,
                                     changedAt: Date(timeIntervalSinceReferenceDate: r.3), deviceID: r.4, snapshot: snap)
            }
        }
    }

    /// Distinct earlier text answers for a field, most recent first (autocomplete).
    public func recentTextValues(measureID: UUID, fieldKey: String, limit: Int = 12) -> [String] {
        var seen = Set<String>()
        var out: [String] = []
        for e in entries(measureID: measureID, limit: 300) {
            guard let t = e.values[fieldKey]?.text?.trimmingCharacters(in: .whitespaces), !t.isEmpty,
                  seen.insert(t.lowercased()).inserted else { continue }
            out.append(t)
            if out.count >= limit { break }
        }
        return out
    }

    // MARK: - Check-in sessions

    private func _session(_ id: UUID) throws -> CheckInSession? {
        decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions WHERE id = ?", [.text(id.uuidString)]).first
    }

    private func _writeSession(_ s: CheckInSession, pending: Bool) throws {
        try db.run("""
            INSERT INTO sessions(id, kind, day_key, deleted, modified_at, pending, json) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, day_key = excluded.day_key, deleted = excluded.deleted,
              modified_at = excluded.modified_at, pending = excluded.pending, json = excluded.json
            """, [.text(s.id.uuidString), .text(s.kind.rawValue), .text(s.dayKey), .int(s.deletedAt == nil ? 0 : 1),
                  .double(s.modifiedAt.timeIntervalSinceReferenceDate), .int(pending ? 1 : 0), .blob(try encode(s))])
    }

    @discardableResult
    public func saveSession(_ input: CheckInSession) throws -> CheckInSession {
        let saved: CheckInSession = try queue.sync {
            var s = input
            let existing = try _session(s.id)
            s.revision = (existing?.revision ?? 0) + 1
            s.createdAt = existing?.createdAt ?? s.createdAt
            s.modifiedAt = stamp(after: existing?.modifiedAt)
            s.modifiedBy = deviceID
            s.dayKey = DayKey.make(for: s.startedAt, timeZone: s.timeZone, boundaryHour: _settings().dayBoundaryHour)
            try _writeSession(s, pending: true)
            return s
        }
        notifyChange()
        return saved
    }

    public func sessions(dayKey: String) -> [CheckInSession] {
        queue.sync {
            decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions WHERE day_key = ? AND deleted = 0 ORDER BY modified_at",
                       [.text(dayKey)])
        }
    }

    public func allSessions(includeDeleted: Bool = false) -> [CheckInSession] {
        queue.sync {
            decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions" + (includeDeleted ? "" : " WHERE deleted = 0")
                       + " ORDER BY day_key, modified_at")
        }
    }

    /// The completed session of `kind` for a day, if any.
    public func completedSession(_ kind: CheckInKind, dayKey: String) -> CheckInSession? {
        sessions(dayKey: dayKey).last(where: { $0.kind == kind && $0.completedAt != nil })
    }

    // MARK: - Sync

    /// Records changed on this device that the counterpart has not confirmed yet.
    public func pendingChanges(maxEntries: Int = 200) -> SyncBatch {
        queue.sync {
            let measures = decodeRows(Measure.self, sql: "SELECT json FROM measures WHERE pending = 1")
            let entries = decodeRows(Entry.self, sql: "SELECT json FROM entries WHERE pending = 1 ORDER BY modified_at LIMIT ?",
                                     [.int(Int64(maxEntries))])
            let sessions = decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions WHERE pending = 1")
            let settingsPending = kvGet("settings_pending") == Data([1])
            return SyncBatch(senderDeviceID: deviceID, sentAt: now(), measures: measures, entries: entries,
                             sessions: sessions, settings: settingsPending ? _settings() : nil, isFullSnapshot: false)
        }
    }

    public var hasPendingChanges: Bool {
        queue.sync {
            let n = (try? db.query("""
                SELECT (SELECT COUNT(*) FROM measures WHERE pending = 1) + (SELECT COUNT(*) FROM entries WHERE pending = 1)
                     + (SELECT COUNT(*) FROM sessions WHERE pending = 1)
                """) { Int($0.int(0)) }.first) ?? 0
            return n > 0 || kvGet("settings_pending") == Data([1])
        }
    }

    /// Everything, for a full resync or backup.
    public func fullSnapshot() -> SyncBatch {
        queue.sync {
            SyncBatch(senderDeviceID: deviceID, sentAt: now(),
                      measures: decodeRows(Measure.self, sql: "SELECT json FROM measures"),
                      entries: decodeRows(Entry.self, sql: "SELECT json FROM entries ORDER BY occurred_at"),
                      sessions: decodeRows(CheckInSession.self, sql: "SELECT json FROM sessions"),
                      settings: _settings(), isFullSnapshot: true)
        }
    }

    /// Clears pending flags for records whose current version is the one that was sent.
    public func markSynced(_ receipt: SyncReceipt) throws {
        try queue.sync {
            try db.transaction {
                for (table, stamps) in [("measures", receipt.measures), ("entries", receipt.entries), ("sessions", receipt.sessions)] {
                    for s in stamps {
                        try db.run("UPDATE \(table) SET pending = 0 WHERE id = ? AND ABS(modified_at - ?) < 0.0005",
                                   [.text(s.id.uuidString), .double(s.modifiedAt.timeIntervalSinceReferenceDate)])
                    }
                }
                if let sent = receipt.settingsModifiedAt, abs(_settings().modifiedAt.timeIntervalSince(sent)) < 0.0005 {
                    try kvSet("settings_pending", Data([0]))
                }
            }
        }
    }

    /// Marks every record as pending (used before a full resync).
    public func markAllPending() throws {
        try queue.sync {
            try db.execute("UPDATE measures SET pending = 1; UPDATE entries SET pending = 1; UPDATE sessions SET pending = 1;")
            try kvSet("settings_pending", Data([1]))
        }
    }

    /// Merges records from another device (or a backup) using last-writer-wins.
    /// Applied records are not marked pending, so they are not echoed back.
    @discardableResult
    public func apply(_ batch: SyncBatch, changeKind: ChangeKind = .synced) throws -> SyncApplyResult {
        let result: SyncApplyResult = try queue.sync {
            var result = SyncApplyResult()
            try db.transaction {
                if let remote = batch.settings {
                    let local = _settings()
                    if Conflict.remoteWins(local: (local.modifiedAt, local.modifiedBy), remote: (remote.modifiedAt, remote.modifiedBy)) {
                        try kvSet("settings", try encode(remote))
                        cachedSettings = remote
                        if local.dayBoundaryHour != remote.dayBoundaryHour { try _recomputeDayKeys(boundary: remote.dayBoundaryHour) }
                        result.settingsUpdated = true
                    }
                }
                for m in batch.measures {
                    let local = try _measure(m.id)
                    if let local, !Conflict.remoteWins(local: (local.modifiedAt, local.modifiedBy), remote: (m.modifiedAt, m.modifiedBy)) {
                        result.ignored += 1
                        continue
                    }
                    try _writeMeasure(m, pending: false)
                    try _logMeasureRevision(m)
                    if local == nil { result.inserted += 1 } else { result.updated += 1 }
                }
                let boundary = _settings().dayBoundaryHour
                for var e in batch.entries {
                    let local = try _entry(e.id)
                    if let local, !Conflict.remoteWins(local: (local.modifiedAt, local.modifiedBy), remote: (e.modifiedAt, e.modifiedBy)) {
                        result.ignored += 1
                        continue
                    }
                    e.dayKey = DayKey.make(for: e.occurredAt, timeZone: e.timeZone, boundaryHour: boundary)
                    try _writeEntry(e, pending: false)
                    try _logEntryRevision(e, kind: changeKind)
                    if local == nil { result.inserted += 1 } else { result.updated += 1 }
                }
                for var s in batch.sessions {
                    let local = try _session(s.id)
                    if let local, !Conflict.remoteWins(local: (local.modifiedAt, local.modifiedBy), remote: (s.modifiedAt, s.modifiedBy)) {
                        result.ignored += 1
                        continue
                    }
                    s.dayKey = DayKey.make(for: s.startedAt, timeZone: s.timeZone, boundaryHour: boundary)
                    try _writeSession(s, pending: false)
                    if local == nil { result.inserted += 1 } else { result.updated += 1 }
                }
            }
            return result
        }
        if result.changedAnything { notifyChange() }
        return result
    }
}
