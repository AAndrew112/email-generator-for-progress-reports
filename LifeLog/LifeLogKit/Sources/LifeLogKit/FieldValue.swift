import Foundation

/// A single recorded value. A field that was never answered has *no* value
/// (it is absent from `Entry.values`), which is how LifeLog keeps "missing"
/// distinct from zero, "No", or an empty selection.
public enum FieldValue: Hashable, Sendable {
    /// Ratings and numbers.
    case number(Double)
    case bool(Bool)
    case text(String)
    /// Selected option keys. Single-choice fields hold exactly one key.
    case choices([String])
    /// A clock time / timestamp.
    case date(Date)
    /// A length of time in seconds.
    case duration(TimeInterval)
    /// Photo file names stored in the private photo directory.
    case photos([String])

    public var number: Double? {
        switch self {
        case .number(let v): return v
        case .duration(let v): return v
        case .bool(let b): return b ? 1 : 0
        default: return nil
        }
    }

    public var bool: Bool? { if case .bool(let b) = self { return b } else { return nil } }
    public var text: String? { if case .text(let t) = self { return t } else { return nil } }
    public var choiceKeys: [String] { if case .choices(let c) = self { return c } else { return [] } }
    public var date: Date? { if case .date(let d) = self { return d } else { return nil } }
    public var duration: TimeInterval? { if case .duration(let d) = self { return d } else { return nil } }
    public var photoNames: [String] { if case .photos(let p) = self { return p } else { return [] } }

    /// True when the value carries no information (empty text, no selection, no photos).
    /// Such values are dropped before saving so they never masquerade as answers.
    public var isEmpty: Bool {
        switch self {
        case .text(let t): return t.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .choices(let c): return c.isEmpty
        case .photos(let p): return p.isEmpty
        case .number(let v), .duration(let v): return !v.isFinite
        default: return false
        }
    }

    public var typeTag: String {
        switch self {
        case .number: return "number"
        case .bool: return "bool"
        case .text: return "text"
        case .choices: return "choices"
        case .date: return "date"
        case .duration: return "duration"
        case .photos: return "photos"
        }
    }
}

extension FieldValue: Codable {
    private enum CodingKeys: String, CodingKey { case type, value }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let type = try c.decode(String.self, forKey: .type)
        switch type {
        case "number": self = .number(try c.decode(Double.self, forKey: .value))
        case "bool": self = .bool(try c.decode(Bool.self, forKey: .value))
        case "text": self = .text(try c.decode(String.self, forKey: .value))
        case "choices": self = .choices(try c.decode([String].self, forKey: .value))
        case "date": self = .date(try c.decode(Date.self, forKey: .value))
        case "duration": self = .duration(try c.decode(Double.self, forKey: .value))
        case "photos": self = .photos(try c.decode([String].self, forKey: .value))
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: c,
                                                   debugDescription: "Unknown FieldValue type \(type)")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(typeTag, forKey: .type)
        switch self {
        case .number(let v): try c.encode(v, forKey: .value)
        case .bool(let v): try c.encode(v, forKey: .value)
        case .text(let v): try c.encode(v, forKey: .value)
        case .choices(let v): try c.encode(v, forKey: .value)
        case .date(let v): try c.encode(v, forKey: .value)
        case .duration(let v): try c.encode(v, forKey: .value)
        case .photos(let v): try c.encode(v, forKey: .value)
        }
    }
}
