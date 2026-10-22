import Foundation

/// A bounded study period (e.g. a 42-day protocol). Exports gain `study` and
/// `study_day` columns for days that fall inside it.
public struct Study: Codable, Hashable, Sendable, Identifiable {
    public var id: UUID
    public var name: String
    /// First day, "yyyy-MM-dd".
    public var startDay: String
    public var lengthDays: Int

    public init(id: UUID = UUID(), name: String, startDay: String, lengthDays: Int) {
        self.id = id
        self.name = name
        self.startDay = startDay
        self.lengthDays = lengthDays
    }

    /// 1-based day number, or nil when `dayKey` is outside the study.
    public func dayNumber(for dayKey: String) -> Int? {
        guard let offset = DayKey.daysBetween(startDay, dayKey) else { return nil }
        let n = offset + 1
        return (1...max(1, lengthDays)).contains(n) ? n : nil
    }

    public var endDay: String { DayKey.adding(days: max(0, lengthDays - 1), to: startDay) ?? startDay }
}

public struct ReminderTime: Codable, Hashable, Sendable {
    public var hour: Int
    public var minute: Int
    public var isEnabled: Bool
    public init(hour: Int, minute: Int, isEnabled: Bool) {
        self.hour = hour
        self.minute = minute
        self.isEnabled = isEnabled
    }
}

/// Settings shared between iPhone and Watch (synced, last writer wins).
public struct AppSettings: Codable, Hashable, Sendable {
    /// Events before this hour count toward the previous day (default 4 AM).
    public var dayBoundaryHour: Int
    public var studies: [Study]
    public var morningReminder: ReminderTime
    public var eveningReminder: ReminderTime
    public var healthKitSleepPrefill: Bool
    /// Hour after which the app suggests the evening check-in instead of the morning one.
    public var eveningStartsHour: Int
    public var modifiedAt: Date
    public var modifiedBy: String

    public init(dayBoundaryHour: Int = 4, studies: [Study] = [],
                morningReminder: ReminderTime = .init(hour: 8, minute: 0, isEnabled: false),
                eveningReminder: ReminderTime = .init(hour: 21, minute: 30, isEnabled: false),
                healthKitSleepPrefill: Bool = false, eveningStartsHour: Int = 17,
                modifiedAt: Date = Date(timeIntervalSinceReferenceDate: 0), modifiedBy: String = "") {
        self.dayBoundaryHour = dayBoundaryHour
        self.studies = studies
        self.morningReminder = morningReminder
        self.eveningReminder = eveningReminder
        self.healthKitSleepPrefill = healthKitSleepPrefill
        self.eveningStartsHour = eveningStartsHour
        self.modifiedAt = modifiedAt
        self.modifiedBy = modifiedBy
    }

    private enum CodingKeys: String, CodingKey {
        case dayBoundaryHour, studies, morningReminder, eveningReminder, healthKitSleepPrefill,
             eveningStartsHour, modifiedAt, modifiedBy
    }

    public init(from decoder: Decoder) throws {
        let d = AppSettings()
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dayBoundaryHour = try c.decodeIfPresent(Int.self, forKey: .dayBoundaryHour) ?? d.dayBoundaryHour
        studies = try c.decodeIfPresent([Study].self, forKey: .studies) ?? []
        morningReminder = try c.decodeIfPresent(ReminderTime.self, forKey: .morningReminder) ?? d.morningReminder
        eveningReminder = try c.decodeIfPresent(ReminderTime.self, forKey: .eveningReminder) ?? d.eveningReminder
        healthKitSleepPrefill = try c.decodeIfPresent(Bool.self, forKey: .healthKitSleepPrefill) ?? false
        eveningStartsHour = try c.decodeIfPresent(Int.self, forKey: .eveningStartsHour) ?? d.eveningStartsHour
        modifiedAt = try c.decodeIfPresent(Date.self, forKey: .modifiedAt) ?? d.modifiedAt
        modifiedBy = try c.decodeIfPresent(String.self, forKey: .modifiedBy) ?? ""
    }

    public func study(containing dayKey: String) -> (Study, Int)? {
        for s in studies { if let n = s.dayNumber(for: dayKey) { return (s, n) } }
        return nil
    }

    /// The default study requested at setup: 42 days from 19 October 2026.
    public static let scrollingStudy = Study(
        id: UUID(uuidString: "5D1E0000-0000-4000-8000-000000000042")!,
        name: "Scrolling & focus study", startDay: "2026-10-19", lengthDays: 42)
}

/// Helpers for "yyyy-MM-dd" logical-day keys.
public enum DayKey {
    private static let posix = Locale(identifier: "en_US_POSIX")

    static func calendar(_ tz: TimeZone) -> Calendar {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        cal.locale = posix
        return cal
    }

    /// Logical day for a moment: times before `boundaryHour` belong to the previous day.
    public static func make(for date: Date, timeZone: TimeZone, boundaryHour: Int) -> String {
        let cal = calendar(timeZone)
        let comps = cal.dateComponents([.year, .month, .day, .hour], from: date)
        var y = comps.year ?? 1970, m = comps.month ?? 1, d = comps.day ?? 1
        if (comps.hour ?? 0) < boundaryHour {
            if let prev = cal.date(byAdding: .day, value: -1, to: date) {
                let p = cal.dateComponents([.year, .month, .day], from: prev)
                y = p.year ?? y; m = p.month ?? m; d = p.day ?? d
            }
        }
        return format(year: y, month: m, day: d)
    }

    /// Calendar date (no boundary shift).
    public static func calendarDay(for date: Date, timeZone: TimeZone) -> String {
        make(for: date, timeZone: timeZone, boundaryHour: 0)
    }

    public static func format(year: Int, month: Int, day: Int) -> String {
        String(format: "%04d-%02d-%02d", year, month, day)
    }

    public static func parse(_ key: String) -> (year: Int, month: Int, day: Int)? {
        let parts = key.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return (parts[0], parts[1], parts[2])
    }

    /// Noon UTC of the day, a stable anchor for day arithmetic.
    static func anchor(_ key: String) -> Date? {
        guard let p = parse(key) else { return nil }
        let cal = calendar(TimeZone(identifier: "UTC")!)
        return cal.date(from: DateComponents(year: p.year, month: p.month, day: p.day, hour: 12))
    }

    public static func daysBetween(_ from: String, _ to: String) -> Int? {
        guard let a = anchor(from), let b = anchor(to) else { return nil }
        return Int((b.timeIntervalSince(a) / 86_400).rounded())
    }

    public static func adding(days: Int, to key: String) -> String? {
        guard let a = anchor(key) else { return nil }
        let cal = calendar(TimeZone(identifier: "UTC")!)
        guard let d = cal.date(byAdding: .day, value: days, to: a) else { return nil }
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return format(year: c.year!, month: c.month!, day: c.day!)
    }

    /// Every day key from `from` through `to` inclusive.
    public static func range(_ from: String, _ to: String) -> [String] {
        guard let n = daysBetween(from, to), n >= 0 else { return [] }
        return (0...n).compactMap { adding(days: $0, to: from) }
    }

    /// The local-time start of a logical day (its boundary hour).
    public static func start(of key: String, timeZone: TimeZone, boundaryHour: Int) -> Date? {
        guard let p = parse(key) else { return nil }
        return calendar(timeZone).date(from: DateComponents(year: p.year, month: p.month, day: p.day, hour: boundaryHour))
    }

    public static func weekday(_ key: String) -> String {
        guard let a = anchor(key) else { return "" }
        let cal = calendar(TimeZone(identifier: "UTC")!)
        let names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        return names[(cal.component(.weekday, from: a) - 1) % 7]
    }
}
