import Foundation
import LifeLogKit

/// A quick-log button: a measure, optionally with a saved preset.
struct QuickAction: Identifiable, Hashable {
    let measure: Measure
    let preset: Preset?

    var id: String {
        if let preset { return "p:\(measure.id.uuidString):\(preset.id.uuidString)" }
        return "m:\(measure.id.uuidString)"
    }

    var title: String { preset?.label ?? measure.name }
    var subtitle: String? { preset != nil ? measure.name : nil }

    /// Values the entry starts with: field defaults overlaid with the preset.
    var values: [String: FieldValue] {
        measure.defaultValues.merging(preset?.values ?? [:]) { _, new in new }
    }

    /// True when one tap produces a complete entry.
    var isComplete: Bool {
        let v = values
        return measure.activeFields.allSatisfy { !$0.isRequired || v[$0.key] != nil }
    }

    static func find(_ id: String, in measures: [Measure]) -> QuickAction? {
        let parts = id.split(separator: ":").map(String.init)
        guard parts.count >= 2, let mid = UUID(uuidString: parts[1]),
              let m = measures.first(where: { $0.id == mid }) else { return nil }
        if parts[0] == "p", parts.count == 3, let pid = UUID(uuidString: parts[2]) {
            return m.presets.first(where: { $0.id == pid }).map { QuickAction(measure: m, preset: $0) }
        }
        return QuickAction(measure: m, preset: nil)
    }
}

enum QuickLogger {
    /// Favourites in display order: each favourite measure, then its favourite presets.
    static func favorites(from measures: [Measure]) -> [QuickAction] {
        var out: [QuickAction] = []
        for m in measures where m.isActive && m.deletedAt == nil {
            if m.isFavorite { out.append(QuickAction(measure: m, preset: nil)) }
            for p in m.presets where p.isFavorite { out.append(QuickAction(measure: m, preset: p)) }
        }
        return out
    }

    /// Everything that can be quick-logged (measures marked for quick log, plus all presets).
    static func allActions(from measures: [Measure]) -> [QuickAction] {
        var out: [QuickAction] = []
        for m in measures where m.isActive && m.deletedAt == nil && m.inQuickLog {
            out.append(QuickAction(measure: m, preset: nil))
            for p in m.presets { out.append(QuickAction(measure: m, preset: p)) }
        }
        return out
    }

    /// Logs the action right away if it needs no further input; otherwise returns nil
    /// so the caller can ask for the missing values.
    @discardableResult
    static func logIfComplete(_ action: QuickAction, store: Store, context: EntryContext,
                              at date: Date? = nil) throws -> Entry? {
        guard action.isComplete else { return nil }
        if action.measure.cardinality == .oncePerDay {
            let day = store.dayKey(for: date ?? store.now())
            if store.entries(dayKey: day).contains(where: { $0.measureID == action.measure.id }) { return nil }
        }
        var entry = store.makeEntry(for: action.measure, values: action.values, occurredAt: date,
                                    context: context, presetID: action.preset?.id)
        if let f = action.measure.episodeDurationField, let d = entry.values[f.key]?.duration, date == nil {
            // An episode logged "now" just ended: it started `duration` ago.
            entry.setOccurredAt(entry.occurredAt.addingTimeInterval(-d))
        }
        return try store.saveEntry(entry)
    }

    /// How many entries of this action were logged in a day.
    static func count(of action: QuickAction, in entries: [Entry]) -> Int {
        entries.filter { $0.measureID == action.measure.id && (action.preset == nil || $0.presetID == action.preset?.id) }.count
    }
}
