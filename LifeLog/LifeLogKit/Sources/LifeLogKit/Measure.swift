import Foundation

public enum FieldType: String, Codable, CaseIterable, Sendable, Identifiable {
    case rating
    case number
    case boolean
    case choice
    case multiChoice
    case time
    case duration
    case text
    case photo

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .rating: return "Rating scale"
        case .number: return "Number"
        case .boolean: return "Yes / No"
        case .choice: return "Single choice"
        case .multiChoice: return "Multiple choice"
        case .time: return "Time"
        case .duration: return "Duration"
        case .text: return "Text"
        case .photo: return "Photo"
        }
    }

    public var symbolName: String {
        switch self {
        case .rating: return "dial.medium"
        case .number: return "number"
        case .boolean: return "checkmark.circle"
        case .choice: return "list.bullet.circle"
        case .multiChoice: return "checklist"
        case .time: return "clock"
        case .duration: return "timer"
        case .text: return "text.alignleft"
        case .photo: return "camera"
        }
    }
}

public struct RatingAnchor: Codable, Hashable, Sendable {
    public var value: Int
    public var label: String
    public init(value: Int, label: String) {
        self.value = value
        self.label = label
    }
}

public struct ChoiceOption: Codable, Hashable, Sendable, Identifiable {
    /// Stable key written to exports. Never changes after creation.
    public var key: String
    public var label: String
    /// Hidden from pickers but kept so historical values stay interpretable.
    public var isArchived: Bool
    public var id: String { key }

    public init(key: String, label: String, isArchived: Bool = false) {
        self.key = key
        self.label = label
        self.isArchived = isArchived
    }

    public init(_ label: String) {
        self.init(key: Slug.make(label), label: label)
    }

    private enum CodingKeys: String, CodingKey { case key, label, isArchived }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = try c.decode(String.self, forKey: .label)
        isArchived = try c.decodeIfPresent(Bool.self, forKey: .isArchived) ?? false
    }
}

/// How a field is summarised in the one-row-per-day export.
public enum DailyAggregate: String, Codable, CaseIterable, Sendable, Identifiable {
    case automatic, last, first, sum, mean, min, max, count, none
    public var id: String { rawValue }
    public var displayName: String {
        switch self {
        case .automatic: return "Automatic"
        case .last: return "Last value"
        case .first: return "First value"
        case .sum: return "Total"
        case .mean: return "Average"
        case .min: return "Minimum"
        case .max: return "Maximum"
        case .count: return "Count answered"
        case .none: return "Leave out"
        }
    }
}

public struct FieldDefinition: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    /// Stable snake_case key used in storage and exports. Never changes after creation.
    public var key: String
    public var label: String
    /// Question shown to the user. Falls back to `label`.
    public var prompt: String?
    public var type: FieldType
    public var unit: String?
    public var minValue: Double?
    public var maxValue: Double?
    public var step: Double?
    /// Labels for rating points. Ideally every point is labelled.
    public var anchors: [RatingAnchor]
    public var options: [ChoiceOption]
    public var defaultValue: FieldValue?
    public var isRequired: Bool
    /// One-tap chips for number/duration fields (durations in seconds).
    public var quickValues: [Double]
    public var dailyAggregate: DailyAggregate
    public var isArchived: Bool

    public init(id: UUID = UUID(), key: String, label: String, prompt: String? = nil, type: FieldType,
                unit: String? = nil, minValue: Double? = nil, maxValue: Double? = nil, step: Double? = nil,
                anchors: [RatingAnchor] = [], options: [ChoiceOption] = [], defaultValue: FieldValue? = nil,
                isRequired: Bool = false, quickValues: [Double] = [], dailyAggregate: DailyAggregate = .automatic,
                isArchived: Bool = false) {
        self.id = id
        self.key = key
        self.label = label
        self.prompt = prompt
        self.type = type
        self.unit = unit
        self.minValue = minValue
        self.maxValue = maxValue
        self.step = step
        self.anchors = anchors
        self.options = options
        self.defaultValue = defaultValue
        self.isRequired = isRequired
        self.quickValues = quickValues
        self.dailyAggregate = dailyAggregate
        self.isArchived = isArchived
    }

    private enum CodingKeys: String, CodingKey {
        case id, key, label, prompt, type, unit, minValue, maxValue, step, anchors, options,
             defaultValue, isRequired, quickValues, dailyAggregate, isArchived
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        key = try c.decode(String.self, forKey: .key)
        label = try c.decode(String.self, forKey: .label)
        prompt = try c.decodeIfPresent(String.self, forKey: .prompt)
        type = try c.decode(FieldType.self, forKey: .type)
        unit = try c.decodeIfPresent(String.self, forKey: .unit)
        minValue = try c.decodeIfPresent(Double.self, forKey: .minValue)
        maxValue = try c.decodeIfPresent(Double.self, forKey: .maxValue)
        step = try c.decodeIfPresent(Double.self, forKey: .step)
        anchors = try c.decodeIfPresent([RatingAnchor].self, forKey: .anchors) ?? []
        options = try c.decodeIfPresent([ChoiceOption].self, forKey: .options) ?? []
        defaultValue = try c.decodeIfPresent(FieldValue.self, forKey: .defaultValue)
        isRequired = try c.decodeIfPresent(Bool.self, forKey: .isRequired) ?? false
        quickValues = try c.decodeIfPresent([Double].self, forKey: .quickValues) ?? []
        dailyAggregate = try c.decodeIfPresent(DailyAggregate.self, forKey: .dailyAggregate) ?? .automatic
        isArchived = try c.decodeIfPresent(Bool.self, forKey: .isArchived) ?? false
    }

    public var displayPrompt: String { (prompt?.isEmpty == false ? prompt! : label) }

    public var ratingRange: ClosedRange<Int> {
        let lo = Int(minValue ?? 0)
        let hi = Swift.max(lo, Int(maxValue ?? 4))
        return lo...hi
    }

    public func anchorLabel(for value: Int) -> String? {
        anchors.first(where: { $0.value == value })?.label
    }

    public func optionLabel(for key: String) -> String {
        options.first(where: { $0.key == key })?.label ?? key
    }

    public var activeOptions: [ChoiceOption] { options.filter { !$0.isArchived } }

    /// The aggregate actually used in the daily export.
    public func resolvedAggregate(cardinality: Cardinality) -> DailyAggregate {
        guard dailyAggregate == .automatic else { return dailyAggregate }
        if cardinality == .oncePerDay { return type == .photo ? .count : .last }
        switch type {
        case .duration, .number: return .sum
        case .rating: return .mean
        case .boolean: return .sum
        case .photo: return .count
        case .time: return .first
        case .choice, .multiChoice, .text: return .none
        }
    }
}

/// A saved combination of values for one-tap logging ("Coffee · 95 mg").
public struct Preset: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    public var label: String
    public var values: [String: FieldValue]
    public var isFavorite: Bool

    public init(id: UUID = UUID(), label: String, values: [String: FieldValue], isFavorite: Bool = true) {
        self.id = id
        self.label = label
        self.values = values
        self.isFavorite = isFavorite
    }
}

public enum Cardinality: String, Codable, Sendable, CaseIterable, Identifiable {
    /// One answer per day (check-in questions). Logging again edits the day's entry.
    case oncePerDay
    /// Any number of events per day (urges, doses, symptoms).
    case multiple
    public var id: String { rawValue }
    public var displayName: String { self == .oncePerDay ? "Once per day" : "Any time, many per day" }
}

public enum Timing: String, Codable, Sendable, CaseIterable, Identifiable {
    /// The entry happened at a single moment.
    case point
    /// The entry is an episode: `occurredAt` is the start and the measure's
    /// duration field holds its length.
    case episode
    public var id: String { rawValue }
}

public struct Measure: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    /// Stable snake_case key used in exports. Never changes after creation.
    public var key: String
    public var name: String
    /// Optional short description / question shown above the fields.
    public var prompt: String?
    public var group: String
    public var icon: String
    public var color: String
    public var fields: [FieldDefinition]
    public var presets: [Preset]
    public var cardinality: Cardinality
    public var timing: Timing
    public var inMorningCheckIn: Bool
    public var inEveningCheckIn: Bool
    public var inQuickLog: Bool
    public var isFavorite: Bool
    public var isActive: Bool
    public var sortOrder: Int
    public var createdAt: Date
    public var modifiedAt: Date
    public var revision: Int
    public var modifiedBy: String
    public var deletedAt: Date?

    public init(id: UUID = UUID(), key: String, name: String, prompt: String? = nil, group: String,
                icon: String = "circle", color: String = "blue", fields: [FieldDefinition],
                presets: [Preset] = [], cardinality: Cardinality = .multiple, timing: Timing = .point,
                inMorningCheckIn: Bool = false, inEveningCheckIn: Bool = false, inQuickLog: Bool = true,
                isFavorite: Bool = false, isActive: Bool = true, sortOrder: Int = 0,
                createdAt: Date = Date(), modifiedAt: Date = Date(), revision: Int = 0,
                modifiedBy: String = "", deletedAt: Date? = nil) {
        self.id = id
        self.key = key
        self.name = name
        self.prompt = prompt
        self.group = group
        self.icon = icon
        self.color = color
        self.fields = fields
        self.presets = presets
        self.cardinality = cardinality
        self.timing = timing
        self.inMorningCheckIn = inMorningCheckIn
        self.inEveningCheckIn = inEveningCheckIn
        self.inQuickLog = inQuickLog
        self.isFavorite = isFavorite
        self.isActive = isActive
        self.sortOrder = sortOrder
        self.createdAt = createdAt
        self.modifiedAt = modifiedAt
        self.revision = revision
        self.modifiedBy = modifiedBy
        self.deletedAt = deletedAt
    }

    private enum CodingKeys: String, CodingKey {
        case id, key, name, prompt, group, icon, color, fields, presets, cardinality, timing,
             inMorningCheckIn, inEveningCheckIn, inQuickLog, isFavorite, isActive, sortOrder,
             createdAt, modifiedAt, revision, modifiedBy, deletedAt
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        key = try c.decode(String.self, forKey: .key)
        name = try c.decode(String.self, forKey: .name)
        prompt = try c.decodeIfPresent(String.self, forKey: .prompt)
        group = try c.decodeIfPresent(String.self, forKey: .group) ?? "Custom"
        icon = try c.decodeIfPresent(String.self, forKey: .icon) ?? "circle"
        color = try c.decodeIfPresent(String.self, forKey: .color) ?? "blue"
        fields = try c.decodeIfPresent([FieldDefinition].self, forKey: .fields) ?? []
        presets = try c.decodeIfPresent([Preset].self, forKey: .presets) ?? []
        cardinality = try c.decodeIfPresent(Cardinality.self, forKey: .cardinality) ?? .multiple
        timing = try c.decodeIfPresent(Timing.self, forKey: .timing) ?? .point
        inMorningCheckIn = try c.decodeIfPresent(Bool.self, forKey: .inMorningCheckIn) ?? false
        inEveningCheckIn = try c.decodeIfPresent(Bool.self, forKey: .inEveningCheckIn) ?? false
        inQuickLog = try c.decodeIfPresent(Bool.self, forKey: .inQuickLog) ?? true
        isFavorite = try c.decodeIfPresent(Bool.self, forKey: .isFavorite) ?? false
        isActive = try c.decodeIfPresent(Bool.self, forKey: .isActive) ?? true
        sortOrder = try c.decodeIfPresent(Int.self, forKey: .sortOrder) ?? 0
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt) ?? Date(timeIntervalSinceReferenceDate: 0)
        modifiedAt = try c.decodeIfPresent(Date.self, forKey: .modifiedAt) ?? createdAt
        revision = try c.decodeIfPresent(Int.self, forKey: .revision) ?? 0
        modifiedBy = try c.decodeIfPresent(String.self, forKey: .modifiedBy) ?? ""
        deletedAt = try c.decodeIfPresent(Date.self, forKey: .deletedAt)
    }

    public var activeFields: [FieldDefinition] { fields.filter { !$0.isArchived } }

    public func field(_ key: String) -> FieldDefinition? { fields.first(where: { $0.key == key }) }

    /// The field whose value summarises the entry (first active field).
    public var primaryField: FieldDefinition? { activeFields.first }

    /// The duration field that defines an episode's length, if any.
    public var episodeDurationField: FieldDefinition? {
        timing == .episode ? activeFields.first(where: { $0.type == .duration }) : nil
    }

    /// True when a single tap can produce a complete entry: every required field
    /// has a default value (or there are no required fields).
    public var canLogWithOneTap: Bool {
        activeFields.allSatisfy { !$0.isRequired || $0.defaultValue != nil }
    }

    /// Values used when logging with one tap.
    public var defaultValues: [String: FieldValue] {
        var values: [String: FieldValue] = [:]
        for f in activeFields { if let d = f.defaultValue { values[f.key] = d } }
        return values
    }

    public var isInAnyCheckIn: Bool { inMorningCheckIn || inEveningCheckIn }

    public func isIn(_ kind: CheckInKind) -> Bool {
        kind == .morning ? inMorningCheckIn : inEveningCheckIn
    }
}

public enum MeasureValidationError: Error, Equatable, CustomStringConvertible {
    case emptyName
    case invalidKey
    case duplicateMeasureKey(String)
    case noFields
    case duplicateFieldKey(String)
    case emptyFieldLabel
    case invalidRatingRange(String)
    case missingOptions(String)
    case duplicateOptionKey(String)

    public var description: String {
        switch self {
        case .emptyName: return "Give the measure a name."
        case .invalidKey: return "The export key must contain letters or numbers."
        case .duplicateMeasureKey(let k): return "Another measure already uses the key “\(k)”."
        case .noFields: return "Add at least one field."
        case .duplicateFieldKey(let k): return "Two fields share the key “\(k)”."
        case .emptyFieldLabel: return "Every field needs a label."
        case .invalidRatingRange(let f): return "“\(f)” needs a maximum above its minimum (and at most 20 points)."
        case .missingOptions(let f): return "“\(f)” needs at least one option."
        case .duplicateOptionKey(let f): return "“\(f)” has two options with the same name."
        }
    }
}

extension Measure {
    /// Checks a measure before saving. `existingKeys` maps other measures' keys to their IDs.
    public func validate(existingKeys: [String: UUID] = [:]) -> [MeasureValidationError] {
        var errors: [MeasureValidationError] = []
        if name.trimmingCharacters(in: .whitespaces).isEmpty { errors.append(.emptyName) }
        if Slug.make(key) != key || key.isEmpty { errors.append(.invalidKey) }
        if let other = existingKeys[key], other != id { errors.append(.duplicateMeasureKey(key)) }
        if activeFields.isEmpty { errors.append(.noFields) }
        var seen = Set<String>()
        for f in fields {
            if !seen.insert(f.key).inserted { errors.append(.duplicateFieldKey(f.key)) }
            if f.isArchived { continue }
            if f.label.trimmingCharacters(in: .whitespaces).isEmpty { errors.append(.emptyFieldLabel) }
            if f.type == .rating {
                let lo = f.minValue ?? 0, hi = f.maxValue ?? 4
                if hi <= lo || hi - lo > 20 { errors.append(.invalidRatingRange(f.label)) }
            }
            if f.type == .choice || f.type == .multiChoice {
                if f.activeOptions.isEmpty { errors.append(.missingOptions(f.label)) }
                if Set(f.options.map(\.key)).count != f.options.count { errors.append(.duplicateOptionKey(f.label)) }
            }
        }
        return errors
    }
}

public enum Slug {
    /// Converts a label into a stable snake_case key ("Brain fog!" → "brain_fog").
    public static func make(_ text: String) -> String {
        let folded = text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
        var out = ""
        var lastUnderscore = false
        for scalar in folded.unicodeScalars {
            if CharacterSet.alphanumerics.contains(scalar) && scalar.isASCII {
                out.unicodeScalars.append(scalar)
                lastUnderscore = false
            } else if !lastUnderscore && !out.isEmpty {
                out.append("_")
                lastUnderscore = true
            }
        }
        while out.hasSuffix("_") { out.removeLast() }
        out = out.lowercased()
        if let first = out.first, first.isNumber { out = "m_" + out }
        return out
    }

    /// Makes `base` unique among `existing` by appending _2, _3, ...
    public static func unique(_ base: String, existing: Set<String>) -> String {
        let root = base.isEmpty ? "item" : base
        if !existing.contains(root) { return root }
        var i = 2
        while existing.contains("\(root)_\(i)") { i += 1 }
        return "\(root)_\(i)"
    }
}
