import Foundation

public struct ExportOptions: Sendable {
    public var includeDeleted: Bool
    public var includePhotos: Bool
    public var appVersion: String
    public init(includeDeleted: Bool = false, includePhotos: Bool = true, appVersion: String = "") {
        self.includeDeleted = includeDeleted
        self.includePhotos = includePhotos
        self.appVersion = appVersion
    }
}

public struct ExportResult: Sendable {
    public var directory: URL
    public var files: [String]
    public var entryCount: Int
    public var observationCount: Int
    public var dayCount: Int
    public var photoCount: Int
    public var missingPhotos: Int
}

/// RFC 4180 CSV.
public struct CSVTable {
    public var header: [String]
    public var rows: [[String]] = []

    public init(header: [String]) { self.header = header }

    public mutating func append(_ row: [String]) { rows.append(row) }

    public static func escape(_ field: String) -> String {
        if field.contains(where: { $0 == "," || $0 == "\"" || $0 == "\n" || $0 == "\r" }) || field.hasPrefix(" ") || field.hasSuffix(" ") {
            return "\"" + field.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return field
    }

    public func render() -> String {
        var out = header.map(CSVTable.escape).joined(separator: ",") + "\n"
        for r in rows {
            var row = r
            if row.count < header.count { row += Array(repeating: "", count: header.count - row.count) }
            out += row.map(CSVTable.escape).joined(separator: ",") + "\n"
        }
        return out
    }

    public func write(to url: URL) throws {
        try Data(render().utf8).write(to: url, options: .atomic)
    }
}

/// Formats timestamps as ISO 8601 in the zone where they were recorded.
final class TimestampFormatter {
    private var local: [String: ISO8601DateFormatter] = [:]
    private let utcFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    func local(_ date: Date, _ tz: TimeZone) -> String {
        let key = tz.identifier
        let f: ISO8601DateFormatter
        if let cached = local[key] {
            f = cached
        } else {
            f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime]
            f.timeZone = tz
            local[key] = f
        }
        return f.string(from: date)
    }

    func utc(_ date: Date) -> String { utcFormatter.string(from: date) }

    /// Clock time as decimal hours (07:30 → 7.5) in the given zone.
    func clockHours(_ date: Date, _ tz: TimeZone) -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        let c = cal.dateComponents([.hour, .minute, .second], from: date)
        let h = Double(c.hour ?? 0) + Double(c.minute ?? 0) / 60 + Double(c.second ?? 0) / 3600
        return ValueText.number((h * 10_000).rounded() / 10_000)
    }
}

/// Writes a self-describing export folder:
/// README.txt, measures.csv, entries.csv, observations.csv, daily.csv,
/// checkins.csv, edit_history.csv, lifelog.json and photos/.
public final class Exporter {
    private let store: Store
    private let photoDirectory: URL?
    private let ts = TimestampFormatter()

    public init(store: Store, photoDirectory: URL?) {
        self.store = store
        self.photoDirectory = photoDirectory
    }

    public func export(to dir: URL, options: ExportOptions = ExportOptions()) throws -> ExportResult {
        let fm = FileManager.default
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)

        let settings = store.settings()
        let measures = store.measures(includeDeleted: true)
        let byID = Dictionary(measures.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let entries = store.allEntries(includeDeleted: options.includeDeleted)
        let liveEntries = entries.filter { !$0.isDeleted }
        let sessions = store.allSessions()

        var files: [String] = []
        func save(_ table: CSVTable, _ name: String) throws {
            try table.write(to: dir.appendingPathComponent(name))
            files.append(name)
        }

        try save(measuresTable(measures), "measures.csv")
        try save(entriesTable(entries, byID, settings), "entries.csv")
        let obs = observationsTable(entries, byID, settings)
        try save(obs, "observations.csv")
        let daily = dailyTable(liveEntries, sessions, measures, settings)
        try save(daily, "daily.csv")
        try save(checkInsTable(sessions, settings), "checkins.csv")
        try save(historyTable(store.entryRevisions()), "edit_history.csv")

        // Full-fidelity JSON.
        let full = FullExport(format: FullExport.formatName, schemaVersion: FullExport.currentSchema,
                              exportedAt: store.now(), appVersion: options.appVersion, deviceID: store.deviceID,
                              settings: settings, measures: measures, measureRevisions: store.measureRevisions(),
                              entries: store.allEntries(includeDeleted: true), sessions: store.allSessions(includeDeleted: true),
                              entryRevisions: store.entryRevisions())
        try FullExport.encoder().encode(full).write(to: dir.appendingPathComponent("lifelog.json"), options: .atomic)
        files.append("lifelog.json")

        // Photos.
        var photoCount = 0, missing = 0
        if options.includePhotos, let src = photoDirectory {
            let names = Set(entries.flatMap { $0.values.values.flatMap(\.photoNames) })
            if !names.isEmpty {
                let dst = dir.appendingPathComponent("photos", isDirectory: true)
                try fm.createDirectory(at: dst, withIntermediateDirectories: true)
                for name in names.sorted() {
                    let from = src.appendingPathComponent(name)
                    guard fm.fileExists(atPath: from.path) else { missing += 1; continue }
                    let to = dst.appendingPathComponent(name)
                    try? fm.removeItem(at: to)
                    try fm.copyItem(at: from, to: to)
                    photoCount += 1
                }
                files.append("photos/")
            }
        }

        try Data(readme(settings: settings, options: options, photoCount: photoCount).utf8)
            .write(to: dir.appendingPathComponent("README.txt"), options: .atomic)
        files.insert("README.txt", at: 0)

        return ExportResult(directory: dir, files: files, entryCount: entries.count, observationCount: obs.rows.count,
                            dayCount: daily.rows.count, photoCount: photoCount, missingPhotos: missing)
    }

    // MARK: Tables

    static func exportUnit(_ f: FieldDefinition) -> String {
        switch f.type {
        case .duration: return "minutes"
        case .time: return "ISO 8601 local time"
        case .boolean: return "1 = yes, 0 = no"
        default: return f.unit ?? ""
        }
    }

    func measuresTable(_ measures: [Measure]) -> CSVTable {
        var t = CSVTable(header: ["measure_key", "measure_name", "measure_id", "group", "measure_revision", "active",
                                  "deleted", "cardinality", "timing", "in_morning_checkin", "in_evening_checkin",
                                  "quick_log", "field_key", "field_label", "field_prompt", "field_type", "unit",
                                  "min", "max", "anchors", "options", "required", "daily_aggregate", "field_archived"])
        for m in measures {
            for f in m.fields {
                t.append([m.key, m.name, m.id.uuidString, m.group, String(m.revision), flag(m.isActive),
                          flag(m.deletedAt != nil), m.cardinality.rawValue, m.timing.rawValue,
                          flag(m.inMorningCheckIn), flag(m.inEveningCheckIn), flag(m.inQuickLog),
                          f.key, f.label, f.prompt ?? "", f.type.rawValue, Exporter.exportUnit(f),
                          f.minValue.map(ValueText.number) ?? "", f.maxValue.map(ValueText.number) ?? "",
                          f.anchors.map { "\($0.value)=\($0.label)" }.joined(separator: " | "),
                          f.options.map { "\($0.key)=\($0.label)\($0.isArchived ? " (archived)" : "")" }.joined(separator: " | "),
                          flag(f.isRequired), f.resolvedAggregate(cardinality: m.cardinality).rawValue, flag(f.isArchived)])
            }
        }
        return t
    }

    private func flag(_ b: Bool) -> String { b ? "1" : "0" }

    private func studyCells(_ dayKey: String, _ settings: AppSettings) -> [String] {
        if let (s, n) = settings.study(containing: dayKey) { return [s.name, String(n)] }
        return ["", ""]
    }

    func entriesTable(_ entries: [Entry], _ byID: [UUID: Measure], _ settings: AppSettings) -> CSVTable {
        var t = CSVTable(header: ["entry_id", "measure_key", "measure_name", "measure_revision", "occurred_at",
                                  "ended_at", "occurred_at_utc", "time_zone", "utc_offset_minutes", "local_date", "day",
                                  "study", "study_day", "context", "source", "preset", "summary", "note", "backdated",
                                  "created_at", "modified_at", "revision", "origin_device", "deleted_at", "checkin_id"])
        for e in entries {
            let m = byID[e.measureID]
            let tz = e.timeZone
            let preset = e.presetID.flatMap { pid in m?.presets.first(where: { $0.id == pid })?.label } ?? ""
            let ended: String = e.endedAt(for: m).map { ts.local($0, tz) } ?? ""
            let deletedAt: String = e.deletedAt.map { ts.local($0, tz) } ?? ""
            var row: [String] = [e.id.uuidString, e.measureKey, m?.name ?? "", String(e.measureRevision)]
            row += [ts.local(e.occurredAt, tz), ended, ts.utc(e.occurredAt), e.timeZoneID]
            row += [String(e.utcOffsetSeconds / 60), DayKey.calendarDay(for: e.occurredAt, timeZone: tz), e.dayKey]
            row += studyCells(e.dayKey, settings)
            row += [e.context.rawValue, e.source.rawValue, preset, ValueText.summary(of: e, measure: m), e.note ?? ""]
            row += [flag(e.isBackdated), ts.local(e.createdAt, tz), ts.local(e.modifiedAt, tz), String(e.revision)]
            row += [e.originDevice, deletedAt, e.sessionID?.uuidString ?? ""]
            t.append(row)
        }
        return t
    }

    /// (value, value_numeric, value_label, unit) for one field value.
    func cells(_ v: FieldValue, _ f: FieldDefinition?, _ tz: TimeZone) -> (String, String, String, String) {
        let unit = f.map(Exporter.exportUnit) ?? ""
        switch v {
        case .number(let n):
            let label = f?.type == .rating ? (f?.anchorLabel(for: Int(n.rounded())) ?? "") : ""
            return (ValueText.number(n), ValueText.number(n), label, unit)
        case .bool(let b):
            return (b ? "true" : "false", b ? "1" : "0", b ? "Yes" : "No", unit)
        case .text(let s):
            return (s, "", "", unit)
        case .choices(let keys):
            return (keys.joined(separator: "|"), "", keys.map { f?.optionLabel(for: $0) ?? $0 }.joined(separator: "|"), unit)
        case .date(let d):
            return (ts.local(d, tz), ts.clockHours(d, tz), "", unit)
        case .duration(let s):
            let minutes = ValueText.number((s / 60 * 1000).rounded() / 1000)
            return (minutes, minutes, ValueText.duration(s), "minutes")
        case .photos(let names):
            return (names.map { "photos/\($0)" }.joined(separator: "|"), String(names.count), "", "")
        }
    }

    func observationsTable(_ entries: [Entry], _ byID: [UUID: Measure], _ settings: AppSettings) -> CSVTable {
        var t = CSVTable(header: ["entry_id", "measure_key", "field_key", "field_label", "field_type", "value",
                                  "value_numeric", "value_label", "unit", "occurred_at", "occurred_at_utc", "time_zone",
                                  "local_date", "day", "study", "study_day", "context", "source", "deleted"])
        for e in entries {
            let m = byID[e.measureID]
            let tz = e.timeZone
            var keys = m?.fields.map(\.key).filter { e.values[$0] != nil } ?? []
            keys += e.values.keys.filter { !keys.contains($0) }.sorted()
            for k in keys {
                guard let v = e.values[k] else { continue }
                let f = m?.field(k)
                let (value, numeric, label, unit) = cells(v, f, tz)
                t.append([e.id.uuidString, e.measureKey, k, f?.label ?? k, f?.type.rawValue ?? v.typeTag, value, numeric,
                          label, unit, ts.local(e.occurredAt, tz), ts.utc(e.occurredAt), e.timeZoneID,
                          DayKey.calendarDay(for: e.occurredAt, timeZone: tz), e.dayKey]
                         + studyCells(e.dayKey, settings)
                         + [e.context.rawValue, e.source.rawValue, flag(e.isDeleted)])
            }
        }
        return t
    }

    struct DailyColumn {
        let name: String
        let measure: Measure
        let field: FieldDefinition?   // nil → entry count
        let aggregate: DailyAggregate
    }

    func dailyColumns(_ measures: [Measure], _ entries: [Entry]) -> [DailyColumn] {
        let used = Set(entries.map(\.measureID))
        var usedFieldKeys: [UUID: Set<String>] = [:]
        for e in entries { usedFieldKeys[e.measureID, default: []].formUnion(e.values.keys) }
        var cols: [DailyColumn] = []
        for m in measures where used.contains(m.id) || (m.isActive && m.deletedAt == nil) {
            let fields = m.fields.filter { !$0.isArchived || usedFieldKeys[m.id]?.contains($0.key) == true }
            if m.cardinality == .multiple { cols.append(DailyColumn(name: "\(m.key)__n", measure: m, field: nil, aggregate: .count)) }
            for f in fields {
                let agg = f.resolvedAggregate(cardinality: m.cardinality)
                guard agg != .none && agg != .automatic else { continue }
                let name: String
                if m.cardinality == .oncePerDay {
                    name = fields.count == 1 ? m.key : "\(m.key)__\(f.key)"
                } else {
                    name = "\(m.key)__\(f.key)__\(agg.rawValue)"
                }
                cols.append(DailyColumn(name: name, measure: m, field: f, aggregate: agg))
            }
        }
        return cols
    }

    func dailyTable(_ entries: [Entry], _ sessions: [CheckInSession], _ measures: [Measure], _ settings: AppSettings) -> CSVTable {
        let cols = dailyColumns(measures, entries)
        var t = CSVTable(header: ["day", "weekday", "study", "study_day", "has_data", "morning_checkin_at",
                                  "evening_checkin_at"] + cols.map(\.name))
        let completed = sessions.filter { $0.completedAt != nil }
        let dataDays = Set(entries.map(\.dayKey)).union(completed.map(\.dayKey))
        guard let first = dataDays.min(), let last = dataDays.max() else { return t }
        var byDay: [String: [UUID: [Entry]]] = [:]
        for e in entries { byDay[e.dayKey, default: [:]][e.measureID, default: []].append(e) }

        for day in DayKey.range(first, last) {
            let hasData = dataDays.contains(day)
            func sessionTime(_ k: CheckInKind) -> String {
                guard let s = completed.last(where: { $0.dayKey == day && $0.kind == k }), let c = s.completedAt else { return "" }
                return ts.local(c, s.timeZone)
            }
            var row = [day, DayKey.weekday(day)] + studyCells(day, settings)
                + [flag(hasData), sessionTime(.morning), sessionTime(.evening)]
            for col in cols {
                let es = (byDay[day]?[col.measure.id] ?? []).sorted { $0.occurredAt < $1.occurredAt }
                row.append(aggregateCell(col, es, hasData: hasData))
            }
            t.append(row)
        }
        return t
    }

    func aggregateCell(_ col: DailyColumn, _ entries: [Entry], hasData: Bool) -> String {
        guard let f = col.field else { return hasData ? String(entries.count) : "" }
        let pairs: [(FieldValue, TimeZone)] = entries.compactMap { e in e.values[f.key].map { ($0, e.timeZone) } }
        let isMultiple = col.measure.cardinality == .multiple
        func scalar(_ v: FieldValue, _ tz: TimeZone) -> String {
            switch v {
            case .number(let n): return ValueText.number(n)
            case .duration(let s): return ValueText.number((s / 60 * 1000).rounded() / 1000)
            case .bool(let b): return b ? "1" : "0"
            case .choices(let k): return k.joined(separator: "|")
            case .date(let d): return ts.local(d, tz)
            case .text(let s): return s
            case .photos(let p): return String(p.count)
            }
        }
        let numbers = pairs.compactMap { (v, _) -> Double? in
            if case .duration(let s) = v { return s / 60 }
            if case .photos(let p) = v { return Double(p.count) }
            return v.number
        }
        func num(_ d: Double) -> String { ValueText.number((d * 1000).rounded() / 1000) }
        switch col.aggregate {
        case .last: return pairs.last.map { scalar($0.0, $0.1) } ?? ""
        case .first: return pairs.first.map { scalar($0.0, $0.1) } ?? ""
        case .count: return (hasData || !pairs.isEmpty) ? String(pairs.count) : ""
        case .sum:
            if numbers.isEmpty { return (isMultiple && hasData) ? "0" : "" }
            return num(numbers.reduce(0, +))
        case .mean: return numbers.isEmpty ? "" : num(numbers.reduce(0, +) / Double(numbers.count))
        case .min, .max:
            if f.type == .time {
                let dated = pairs.compactMap { p in p.0.date.map { ($0, p.1) } }.sorted { $0.0 < $1.0 }
                guard let pick = col.aggregate == .min ? dated.first : dated.last else { return "" }
                return ts.local(pick.0, pick.1)
            }
            guard let v = col.aggregate == .min ? numbers.min() : numbers.max() else { return "" }
            return num(v)
        case .none, .automatic: return ""
        }
    }

    func checkInsTable(_ sessions: [CheckInSession], _ settings: AppSettings) -> CSVTable {
        var t = CSVTable(header: ["checkin_id", "kind", "day", "study", "study_day", "started_at", "completed_at",
                                  "time_zone", "presented", "answered", "skipped", "note", "source", "modified_at"])
        for s in sessions {
            let tz = s.timeZone
            let completed: String = s.completedAt.map { ts.local($0, tz) } ?? ""
            var row: [String] = [s.id.uuidString, s.kind.rawValue, s.dayKey]
            row += studyCells(s.dayKey, settings)
            row += [ts.local(s.startedAt, tz), completed, s.timeZoneID]
            row += [s.presentedMeasureKeys.joined(separator: "|"), s.answeredMeasureKeys.joined(separator: "|")]
            row += [s.skippedMeasureKeys.joined(separator: "|"), s.note ?? "", s.source.rawValue, ts.local(s.modifiedAt, tz)]
            t.append(row)
        }
        return t
    }

    func historyTable(_ revisions: [EntryRevision]) -> CSVTable {
        var t = CSVTable(header: ["entry_id", "measure_key", "revision", "change_kind", "changed_at_utc", "device",
                                  "occurred_at", "values_json", "note", "deleted"])
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        enc.dateEncodingStrategy = .custom { date, encoder in
            var c = encoder.singleValueContainer()
            try c.encode(FullExport.isoString(date))
        }
        for r in revisions {
            let e = r.snapshot
            let json = (try? enc.encode(e.values)).flatMap { String(data: $0, encoding: .utf8) } ?? ""
            t.append([e.id.uuidString, e.measureKey, String(r.revision), r.changeKind.rawValue, ts.utc(r.changedAt),
                      r.deviceID, ts.local(e.occurredAt, e.timeZone), json, e.note ?? "", flag(e.isDeleted)])
        }
        return t
    }

    func readme(settings: AppSettings, options: ExportOptions, photoCount: Int) -> String {
        """
        LifeLog export
        ==============
        Exported: \(ts.utc(store.now())) (UTC)   App version: \(options.appVersion)
        Day boundary: events before \(settings.dayBoundaryHour):00 local time count toward the previous day ("day" columns).
        \(settings.studies.map { "Study: \($0.name), \($0.startDay) to \($0.endDay) (\($0.lengthDays) days)" }.joined(separator: "\n"))

        Files
        -----
        measures.csv      Data dictionary: one row per measure field, with type, unit, scale anchors and options.
        entries.csv       One row per logged entry (timestamps, source, note, revision, summary).
        observations.csv  Tidy/long format: one row per answered field of each entry. Best for analysis.
        daily.csv         Wide format: one row per day, one column per measure field (see below).
        checkins.csv      Morning/evening check-ins: what was presented, answered and skipped.
        edit_history.csv  Every saved version of every entry (audit trail), including deletions.
        lifelog.json      Complete machine-readable export (including deleted entries and definition history).
        photos/           Photos referenced by observations.csv (value column holds relative paths). \(photoCount) included.

        Conventions
        -----------
        * Missing is never zero. A field that was not answered has no row in observations.csv and an empty cell
          in daily.csv. Zero only appears when 0 was recorded, or as a count/total on a day that has data.
        * daily.csv has a row for every day between the first and last day with data. has_data = 1 when the day
          has at least one entry or completed check-in. Count (__n) and total (__sum) columns are 0 on such days
          when nothing was logged, and empty on days with no data at all.
        * Column names: once-per-day measures use <measure> (single field) or <measure>__<field>; repeated
          measures use <measure>__n for the number of entries and <measure>__<field>__<aggregate>.
        * Timestamps are ISO 8601 with the UTC offset in force where they were recorded (occurred_at), plus a
          UTC copy (occurred_at_utc). local_date is the calendar date; day applies the day boundary.
        * For episodes (e.g. scrolling), occurred_at is the start and ended_at = start + duration.
        * Durations are minutes. Time-of-day fields: value is an ISO timestamp, value_numeric is clock hours (7.5 = 07:30).
        * Ratings: value_numeric is the scale point; value_label is its anchor text (see measures.csv).
        * Multiple selections are separated by "|" (option keys in value, labels in value_label).
        * Keys (measure_key, field_key, option keys) never change, even if labels are edited. Removed fields and
          options are kept as archived so older data stays interpretable. measure_revision identifies the
          definition version in force when an entry was saved; lifelog.json holds every version.
        * backdated = 1 when an entry's time differs by more than 10 minutes from when it was first recorded.
        \(options.includeDeleted ? "* Deleted entries are included (deleted = 1 / deleted_at set)." : "* Deleted entries are excluded here but remain in edit_history.csv.")

        Python:  pd.read_csv("observations.csv", parse_dates=["occurred_at_utc"])
        R:       readr::read_csv("daily.csv")
        """
    }
}

/// The complete JSON export; also accepted by `BackupImporter`.
public struct FullExport: Codable {
    public static let formatName = "lifelog-export"
    public static let currentSchema = 1

    public var format: String
    public var schemaVersion: Int
    public var exportedAt: Date
    public var appVersion: String
    public var deviceID: String
    public var settings: AppSettings?
    public var measures: [Measure]
    public var measureRevisions: [MeasureRevision]?
    public var entries: [Entry]
    public var sessions: [CheckInSession]?
    public var entryRevisions: [EntryRevision]?

    static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func isoString(_ date: Date) -> String { isoFractional.string(from: date) }

    public static func encoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.dateEncodingStrategy = .custom { date, encoder in
            var c = encoder.singleValueContainer()
            try c.encode(isoString(date))
        }
        return e
    }

    public static func decoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { decoder in
            let c = try decoder.singleValueContainer()
            if let s = try? c.decode(String.self) {
                if let date = isoFractional.date(from: s) ?? isoPlain.date(from: s) { return date }
                throw DecodingError.dataCorruptedError(in: c, debugDescription: "Bad date \(s)")
            }
            return Date(timeIntervalSinceReferenceDate: try c.decode(Double.self))
        }
        return d
    }
}

public enum BackupImporter {
    public enum ImportError: Error, CustomStringConvertible {
        case notALifeLogExport
        case newerSchema(Int)
        public var description: String {
            switch self {
            case .notALifeLogExport: return "This file isn’t a LifeLog JSON export."
            case .newerSchema(let v): return "This export was made by a newer version of LifeLog (schema \(v))."
            }
        }
    }

    /// Merges a `lifelog.json` export into the store (newer versions win; nothing is duplicated).
    @discardableResult
    public static func importJSON(_ data: Data, into store: Store) throws -> SyncApplyResult {
        let export: FullExport
        do { export = try FullExport.decoder().decode(FullExport.self, from: data) } catch { throw ImportError.notALifeLogExport }
        guard export.format == FullExport.formatName else { throw ImportError.notALifeLogExport }
        guard export.schemaVersion <= FullExport.currentSchema else { throw ImportError.newerSchema(export.schemaVersion) }
        let batch = SyncBatch(senderDeviceID: export.deviceID, sentAt: export.exportedAt, measures: export.measures,
                              entries: export.entries, sessions: export.sessions ?? [], settings: export.settings)
        return try store.apply(batch, changeKind: .imported)
    }
}

/// Private on-device photo storage (file names are random UUIDs; no metadata is kept).
public struct PhotoStore: Sendable {
    public let directory: URL

    public init(directory: URL) {
        self.directory = directory
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    public func url(for name: String) -> URL { directory.appendingPathComponent(name) }

    /// Saves JPEG data and returns the new file name.
    public func save(jpeg data: Data) throws -> String {
        let name = UUID().uuidString.lowercased() + ".jpg"
        #if os(iOS) || os(watchOS)
        try data.write(to: url(for: name), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
        try data.write(to: url(for: name), options: .atomic)
        #endif
        return name
    }

    public func delete(_ name: String) { try? FileManager.default.removeItem(at: url(for: name)) }
}
