import Foundation

/// Human-readable descriptions of values, shared by both apps and the exporter.
public enum ValueText {
    /// "1 h 20 min", "45 min", "30 s".
    public static func duration(_ seconds: TimeInterval) -> String {
        let total = Int(seconds.rounded())
        if total < 60 { return "\(total) s" }
        let minutes = total / 60
        let h = minutes / 60, m = minutes % 60
        if h == 0 { return "\(m) min" }
        return m == 0 ? "\(h) h" : "\(h) h \(m) min"
    }

    /// Compact duration for chips: "45m", "2h", "1.5h".
    public static func shortDuration(_ seconds: TimeInterval) -> String {
        let minutes = Int((seconds / 60).rounded())
        if minutes < 60 { return "\(minutes)m" }
        let h = Double(minutes) / 60
        return h == h.rounded() ? "\(Int(h))h" : String(format: "%.1fh", h)
    }

    /// Plain decimal without trailing zeros ("3", "2.5", "0.125").
    public static func number(_ v: Double) -> String {
        guard v.isFinite else { return "" }
        if v == v.rounded() && abs(v) < 1e15 { return String(Int64(v)) }
        var s = String(format: "%.6f", v)
        while s.hasSuffix("0") { s.removeLast() }
        if s.hasSuffix(".") { s.removeLast() }
        return s
    }

    public static func time(_ date: Date, timeZone: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.timeZone = timeZone
        f.dateStyle = .none
        f.timeStyle = .short
        return f.string(from: date)
    }

    public static func display(_ value: FieldValue, field: FieldDefinition, timeZone: TimeZone = .current) -> String {
        switch (field.type, value) {
        case (.rating, .number(let v)):
            let label = field.anchorLabel(for: Int(v.rounded()))
            return label.map { "\(number(v)) · \($0)" } ?? number(v)
        case (_, .number(let v)):
            return field.unit.map { "\(number(v)) \($0)" } ?? number(v)
        case (_, .bool(let b)):
            return b ? "Yes" : "No"
        case (_, .choices(let keys)):
            return keys.map { field.optionLabel(for: $0) }.joined(separator: ", ")
        case (_, .date(let d)):
            return time(d, timeZone: timeZone)
        case (_, .duration(let s)):
            return duration(s)
        case (_, .text(let t)):
            return t
        case (_, .photos(let p)):
            return p.count == 1 ? "1 photo" : "\(p.count) photos"
        }
    }

    /// One-line summary of an entry ("Resisted · Strong", "Coffee · 95 mg").
    public static func summary(of entry: Entry, measure: Measure?) -> String {
        guard let measure else {
            return entry.values.keys.sorted().compactMap { k in entry.values[k].map { "\(k): \(rawDisplay($0))" } }
                .joined(separator: " · ")
        }
        var parts: [String] = []
        for f in measure.fields {
            guard let v = entry.values[f.key] else { continue }
            var text = display(v, field: f, timeZone: entry.timeZone)
            if f.type == .rating, let label = f.anchorLabel(for: Int(v.number?.rounded() ?? -1)) {
                text = measure.fields.count == 1 ? label : "\(f.label): \(label)"
            } else if f.type == .time {
                text = "\(f.label) \(text)"
            } else if f.type == .boolean {
                text = "\(f.label): \(text)"
            }
            parts.append(text)
        }
        return parts.joined(separator: " · ")
    }

    static func rawDisplay(_ v: FieldValue) -> String {
        switch v {
        case .number(let n): return number(n)
        case .bool(let b): return b ? "Yes" : "No"
        case .text(let t): return t
        case .choices(let c): return c.joined(separator: ", ")
        case .date(let d): return time(d)
        case .duration(let d): return duration(d)
        case .photos(let p): return "\(p.count) photos"
        }
    }
}

/// Pure helpers for turning sleep intervals (e.g. from HealthKit) into the
/// morning check-in's sleep times.
public enum SleepMath {
    public enum Stage: Sendable { case inBed, asleep, awake }

    public struct Interval: Sendable {
        public var start: Date
        public var end: Date
        public var stage: Stage
        public init(start: Date, end: Date, stage: Stage) {
            self.start = start
            self.end = end
            self.stage = stage
        }
    }

    public struct Summary: Equatable, Sendable {
        public var bedtime: Date?
        public var sleepOnset: Date?
        public var wakeTime: Date?
        public var asleepDuration: TimeInterval?
    }

    /// Summarises one night. Overlapping asleep samples from multiple sources are merged.
    public static func summarize(_ intervals: [Interval]) -> Summary {
        let asleep = intervals.filter { $0.stage == .asleep && $0.end > $0.start }.sorted { $0.start < $1.start }
        let inBed = intervals.filter { $0.stage == .inBed && $0.end > $0.start }
        var summary = Summary()
        summary.sleepOnset = asleep.first?.start
        summary.wakeTime = asleep.map(\.end).max()
        summary.bedtime = (inBed.map(\.start) + asleep.prefix(1).map(\.start)).min()
        if !asleep.isEmpty {
            var total: TimeInterval = 0
            var curStart = asleep[0].start, curEnd = asleep[0].end
            for i in asleep.dropFirst() {
                if i.start <= curEnd {
                    curEnd = max(curEnd, i.end)
                } else {
                    total += curEnd.timeIntervalSince(curStart)
                    curStart = i.start
                    curEnd = i.end
                }
            }
            total += curEnd.timeIntervalSince(curStart)
            summary.asleepDuration = total
        }
        return summary
    }

    /// Duration between falling asleep and waking, when plausible (0–20 h).
    public static func duration(onset: Date?, wake: Date?) -> TimeInterval? {
        guard let onset, let wake else { return nil }
        let d = wake.timeIntervalSince(onset)
        return (d > 0 && d < 20 * 3600) ? d : nil
    }

    /// Places a clock time on the right calendar day for "last night":
    /// evening times (after noon) go to the day before `reference`, early times to `reference`'s day.
    public static func lastNight(hour: Int, minute: Int, reference: Date, timeZone: TimeZone = .current) -> Date {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = timeZone
        let today = cal.startOfDay(for: reference)
        let base = hour >= 12 ? cal.date(byAdding: .day, value: -1, to: today)! : today
        return cal.date(bySettingHour: hour, minute: minute, second: 0, of: base) ?? base
    }
}
