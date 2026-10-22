import Foundation

/// Where in the app an entry was recorded.
public enum EntryContext: String, Codable, Sendable, CaseIterable {
    case morningCheckIn = "morning_checkin"
    case eveningCheckIn = "evening_checkin"
    case quickLog = "quick_log"
    case manual = "manual"
    case widget = "widget"
    case shortcut = "shortcut"
    case complication = "complication"
    case importFile = "import"
}

/// Which device or system produced an entry.
public enum EntrySource: String, Codable, Sendable, CaseIterable {
    case iPhone = "iphone"
    case watch = "watch"
    case widget = "widget"
    case healthKit = "healthkit"
    case importFile = "import"
    case other = "other"
}

public struct Entry: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    public var measureID: UUID
    /// Denormalised so exports stay interpretable even if a measure is removed.
    public var measureKey: String
    /// The measure definition revision in force when the entry was last saved.
    public var measureRevision: Int
    /// When the event happened (for episodes: when it started). Editable / backdatable.
    public var occurredAt: Date
    /// Time zone in which the event happened.
    public var timeZoneID: String
    public var utcOffsetSeconds: Int
    /// Logical day ("yyyy-MM-dd") after applying the day-boundary hour.
    public var dayKey: String
    public var values: [String: FieldValue]
    public var note: String?
    public var context: EntryContext
    public var source: EntrySource
    public var sessionID: UUID?
    public var presetID: UUID?
    public var metadata: [String: String]
    public var createdAt: Date
    public var modifiedAt: Date
    public var revision: Int
    public var originDevice: String
    public var modifiedBy: String
    public var deletedAt: Date?

    public init(id: UUID = UUID(), measureID: UUID, measureKey: String, measureRevision: Int = 0,
                occurredAt: Date, timeZone: TimeZone = .current, dayKey: String = "",
                values: [String: FieldValue] = [:], note: String? = nil,
                context: EntryContext = .quickLog, source: EntrySource = .iPhone,
                sessionID: UUID? = nil, presetID: UUID? = nil, metadata: [String: String] = [:],
                createdAt: Date = Date(), modifiedAt: Date = Date(), revision: Int = 0,
                originDevice: String = "", modifiedBy: String = "", deletedAt: Date? = nil) {
        self.id = id
        self.measureID = measureID
        self.measureKey = measureKey
        self.measureRevision = measureRevision
        self.occurredAt = occurredAt
        self.timeZoneID = timeZone.identifier
        self.utcOffsetSeconds = timeZone.secondsFromGMT(for: occurredAt)
        self.dayKey = dayKey
        self.values = values
        self.note = note
        self.context = context
        self.source = source
        self.sessionID = sessionID
        self.presetID = presetID
        self.metadata = metadata
        self.createdAt = createdAt
        self.modifiedAt = modifiedAt
        self.revision = revision
        self.originDevice = originDevice
        self.modifiedBy = modifiedBy
        self.deletedAt = deletedAt
    }

    private enum CodingKeys: String, CodingKey {
        case id, measureID, measureKey, measureRevision, occurredAt, timeZoneID, utcOffsetSeconds, dayKey,
             values, note, context, source, sessionID, presetID, metadata, createdAt, modifiedAt, revision,
             originDevice, modifiedBy, deletedAt
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        measureID = try c.decode(UUID.self, forKey: .measureID)
        measureKey = try c.decode(String.self, forKey: .measureKey)
        measureRevision = try c.decodeIfPresent(Int.self, forKey: .measureRevision) ?? 0
        occurredAt = try c.decode(Date.self, forKey: .occurredAt)
        timeZoneID = try c.decodeIfPresent(String.self, forKey: .timeZoneID) ?? TimeZone.current.identifier
        utcOffsetSeconds = try c.decodeIfPresent(Int.self, forKey: .utcOffsetSeconds)
            ?? (TimeZone(identifier: timeZoneID) ?? .current).secondsFromGMT(for: occurredAt)
        dayKey = try c.decodeIfPresent(String.self, forKey: .dayKey) ?? ""
        values = try c.decodeIfPresent([String: FieldValue].self, forKey: .values) ?? [:]
        note = try c.decodeIfPresent(String.self, forKey: .note)
        context = (try? c.decodeIfPresent(EntryContext.self, forKey: .context)) ?? .manual
        source = (try? c.decodeIfPresent(EntrySource.self, forKey: .source)) ?? .other
        sessionID = try c.decodeIfPresent(UUID.self, forKey: .sessionID)
        presetID = try c.decodeIfPresent(UUID.self, forKey: .presetID)
        metadata = try c.decodeIfPresent([String: String].self, forKey: .metadata) ?? [:]
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt) ?? occurredAt
        modifiedAt = try c.decodeIfPresent(Date.self, forKey: .modifiedAt) ?? createdAt
        revision = try c.decodeIfPresent(Int.self, forKey: .revision) ?? 1
        originDevice = try c.decodeIfPresent(String.self, forKey: .originDevice) ?? ""
        modifiedBy = try c.decodeIfPresent(String.self, forKey: .modifiedBy) ?? originDevice
        deletedAt = try c.decodeIfPresent(Date.self, forKey: .deletedAt)
    }

    public var timeZone: TimeZone { TimeZone(identifier: timeZoneID) ?? TimeZone(secondsFromGMT: utcOffsetSeconds) ?? .current }
    public var isDeleted: Bool { deletedAt != nil }

    /// Changes `occurredAt` and keeps the stored UTC offset consistent with it.
    public mutating func setOccurredAt(_ date: Date, timeZone: TimeZone? = nil) {
        occurredAt = date
        if let tz = timeZone { timeZoneID = tz.identifier }
        utcOffsetSeconds = self.timeZone.secondsFromGMT(for: date)
    }

    /// True when the event time differs meaningfully from when it was first recorded.
    public var isBackdated: Bool { abs(createdAt.timeIntervalSince(occurredAt)) > 10 * 60 }

    /// End of an episode, when the measure defines one.
    public func endedAt(for measure: Measure?) -> Date? {
        guard let f = measure?.episodeDurationField, let d = values[f.key]?.duration else { return nil }
        return occurredAt.addingTimeInterval(d)
    }
}

public enum CheckInKind: String, Codable, Sendable, CaseIterable, Identifiable {
    case morning, evening
    public var id: String { rawValue }
    public var title: String { self == .morning ? "Morning check-in" : "Evening check-in" }
    public var shortTitle: String { self == .morning ? "Morning" : "Evening" }
    public var symbolName: String { self == .morning ? "sunrise.fill" : "moon.stars.fill" }
    public var context: EntryContext { self == .morning ? .morningCheckIn : .eveningCheckIn }
}

/// One run through a check-in. Records which questions were shown, answered or
/// skipped so that "skipped" can be told apart from "never asked".
public struct CheckInSession: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    public var kind: CheckInKind
    public var dayKey: String
    public var startedAt: Date
    public var completedAt: Date?
    public var timeZoneID: String
    public var presentedMeasureKeys: [String]
    public var answeredMeasureKeys: [String]
    public var skippedMeasureKeys: [String]
    public var note: String?
    public var source: EntrySource
    public var createdAt: Date
    public var modifiedAt: Date
    public var revision: Int
    public var modifiedBy: String
    public var deletedAt: Date?

    public init(id: UUID = UUID(), kind: CheckInKind, dayKey: String, startedAt: Date = Date(),
                completedAt: Date? = nil, timeZone: TimeZone = .current, presentedMeasureKeys: [String] = [],
                answeredMeasureKeys: [String] = [], skippedMeasureKeys: [String] = [], note: String? = nil,
                source: EntrySource = .iPhone, createdAt: Date = Date(), modifiedAt: Date = Date(),
                revision: Int = 0, modifiedBy: String = "", deletedAt: Date? = nil) {
        self.id = id
        self.kind = kind
        self.dayKey = dayKey
        self.startedAt = startedAt
        self.completedAt = completedAt
        self.timeZoneID = timeZone.identifier
        self.presentedMeasureKeys = presentedMeasureKeys
        self.answeredMeasureKeys = answeredMeasureKeys
        self.skippedMeasureKeys = skippedMeasureKeys
        self.note = note
        self.source = source
        self.createdAt = createdAt
        self.modifiedAt = modifiedAt
        self.revision = revision
        self.modifiedBy = modifiedBy
        self.deletedAt = deletedAt
    }

    public var timeZone: TimeZone { TimeZone(identifier: timeZoneID) ?? .current }
}

public enum ChangeKind: String, Codable, Sendable {
    case created, updated, deleted, restored, synced, imported
}

/// A snapshot written every time an entry is saved, giving a full edit history.
public struct EntryRevision: Codable, Hashable, Sendable {
    public var entryID: UUID
    public var revision: Int
    public var changeKind: ChangeKind
    public var changedAt: Date
    public var deviceID: String
    public var snapshot: Entry

    public init(entryID: UUID, revision: Int, changeKind: ChangeKind, changedAt: Date, deviceID: String, snapshot: Entry) {
        self.entryID = entryID
        self.revision = revision
        self.changeKind = changeKind
        self.changedAt = changedAt
        self.deviceID = deviceID
        self.snapshot = snapshot
    }
}

/// A snapshot of a measure definition, kept for every saved version.
public struct MeasureRevision: Codable, Hashable, Sendable {
    public var measureID: UUID
    public var revision: Int
    public var changedAt: Date
    public var deviceID: String
    public var snapshot: Measure

    public init(measureID: UUID, revision: Int, changedAt: Date, deviceID: String, snapshot: Measure) {
        self.measureID = measureID
        self.revision = revision
        self.changedAt = changedAt
        self.deviceID = deviceID
        self.snapshot = snapshot
    }
}
