import SwiftUI
import WatchKit
import LifeLogKit

/// Check-in on the Watch: one question per screen, tap an answer to continue.
struct WatchCheckInView: View {
    let kind: CheckInKind
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var measures: [Measure] = []
    @State private var index = 0
    @State private var session: CheckInSession?
    @State private var drafts: [UUID: Entry] = [:]
    @State private var answered: [String] = []
    @State private var skipped: [String] = []
    @State private var started = false

    var body: some View {
        NavigationStack {
            Group {
                if !started {
                    ProgressView()
                } else if measures.isEmpty {
                    Text("No questions in this check-in. Choose them on your iPhone.").font(.footnote)
                } else if index < measures.count {
                    page(measures[index]).id(index)
                } else {
                    done
                }
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { dismiss() } label: { Image(systemName: "xmark") }
                }
            }
        }
        .onAppear(perform: start)
    }

    @ViewBuilder
    private func page(_ m: Measure) -> some View {
        let fields = m.activeFields.filter { $0.type != .photo }
        let tint = Palette.color(m.color)
        if fields.count == 1, let f = fields.first, [.rating, .choice, .boolean, .duration].contains(f.type) {
            WatchFieldPicker(field: f, tint: tint, value: binding(m, f),
                             footer: AnyView(skipButton(m))) { commit(m) }
                .navigationTitle("\(index + 1)/\(measures.count) \(m.name)")
        } else {
            List {
                Section {
                    ForEach(fields) { f in
                        if f.type == .time {
                            DatePicker(f.label, selection: Binding(
                                get: { drafts[m.id]?.values[f.key]?.date ?? defaultTime(f) },
                                set: { setValue(m, f, .date($0)) }), displayedComponents: [.hourAndMinute])
                        } else {
                            NavigationLink {
                                WatchFieldPicker(field: f, tint: tint, value: binding(m, f))
                            } label: {
                                VStack(alignment: .leading) {
                                    Text(f.label).font(.caption).foregroundStyle(.secondary)
                                    Text(drafts[m.id]?.values[f.key].map { ValueText.display($0, field: f) } ?? "—")
                                }
                            }
                        }
                    }
                } header: {
                    Text(m.prompt ?? m.name).textCase(nil)
                }
                Section {
                    Button("Confirm") { commit(m) }.foregroundStyle(tint)
                    skipButton(m)
                }
            }
            .navigationTitle("\(index + 1)/\(measures.count) \(m.name)")
        }
    }

    private func skipButton(_ m: Measure) -> some View {
        Button("Skip") {
            if drafts[m.id]?.revision == 0, !skipped.contains(m.key) { skipped.append(m.key) }
            withAnimation { index += 1 }
        }
        .foregroundStyle(.secondary)
    }

    private var done: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill").font(.system(size: 44)).foregroundStyle(.green)
            Text("\(kind.shortTitle) check-in done").font(.headline).multilineTextAlignment(.center)
            Text("\(answered.count) answered").font(.footnote).foregroundStyle(.secondary)
            Button("Finish") { finish() }
        }
    }

    // MARK: Logic

    private func start() {
        guard !started else { return }
        measures = model.checkInMeasures(kind)
        session = model.startSession(kind, measures: measures)
        for m in measures {
            if m.cardinality == .oncePerDay, let existing = model.todayEntry(for: m) {
                drafts[m.id] = existing
                answered.append(m.key)
            } else {
                var e = model.store.makeEntry(for: m, context: kind.context, sessionID: session?.id)
                if m.key == "sleep_times", let last = model.store.entries(measureID: m.id, limit: 1).first {
                    for key in ["bedtime", "sleep_onset", "wake_time"] {
                        if let d = last.values[key]?.date {
                            let c = Calendar.current.dateComponents([.hour, .minute], from: d)
                            e.values[key] = .date(SleepMath.lastNight(hour: c.hour ?? 0, minute: c.minute ?? 0, reference: Date()))
                        }
                    }
                    if let d = SleepMath.duration(onset: e.values["sleep_onset"]?.date, wake: e.values["wake_time"]?.date) {
                        e.values["sleep_duration"] = .duration(d)
                    }
                    e.metadata["prefill"] = "previous"
                }
                drafts[m.id] = e
            }
        }
        started = true
    }

    private func defaultTime(_ f: FieldDefinition) -> Date {
        switch f.key {
        case "bedtime": return SleepMath.lastNight(hour: 23, minute: 0, reference: Date())
        case "sleep_onset": return SleepMath.lastNight(hour: 23, minute: 20, reference: Date())
        default: return Date()
        }
    }

    private func binding(_ m: Measure, _ f: FieldDefinition) -> Binding<FieldValue?> {
        Binding(get: { drafts[m.id]?.values[f.key] }, set: { setValue(m, f, $0) })
    }

    private func setValue(_ m: Measure, _ f: FieldDefinition, _ value: FieldValue?) {
        guard var e = drafts[m.id] else { return }
        e.values[f.key] = value
        if e.metadata["prefill"] != nil { e.metadata["prefill_edited"] = "1" }
        if m.key == "sleep_times", f.key == "sleep_onset" || f.key == "wake_time",
           let d = SleepMath.duration(onset: e.values["sleep_onset"]?.date, wake: e.values["wake_time"]?.date) {
            e.values["sleep_duration"] = .duration(d)
        }
        drafts[m.id] = e
    }

    private func commit(_ m: Measure) {
        guard var e = drafts[m.id] else { return }
        // Time fields shown with a default count as answered once confirmed.
        for f in m.activeFields where f.type == .time && e.values[f.key] == nil {
            e.values[f.key] = .date(defaultTime(f))
        }
        if m.key == "sleep_times", e.values["sleep_duration"] == nil,
           let d = SleepMath.duration(onset: e.values["sleep_onset"]?.date, wake: e.values["wake_time"]?.date) {
            e.values["sleep_duration"] = .duration(d)
        }
        let required = m.activeFields.filter(\.isRequired)
        guard required.allSatisfy({ e.values[$0.key] != nil }), !e.values.isEmpty else { return }
        if e.revision == 0 { e.setOccurredAt(Date()) }
        if let saved = model.save(e) {
            drafts[m.id] = saved
            skipped.removeAll { $0 == m.key }
            if !answered.contains(m.key) { answered.append(m.key) }
            WKInterfaceDevice.current().play(.click)
            withAnimation { index += 1 }
        }
    }

    private func finish() {
        if var s = session {
            s.completedAt = Date()
            s.answeredMeasureKeys = answered
            s.skippedMeasureKeys = skipped.filter { !answered.contains($0) }
            s.presentedMeasureKeys = measures.map(\.key)
            model.saveSession(s)
        }
        WKInterfaceDevice.current().play(.success)
        dismiss()
    }
}
