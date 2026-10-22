import SwiftUI
import LifeLogKit

/// Morning / evening check-in: one question per page, one tap per rating.
/// Each answer is saved the moment it is given, so quitting halfway loses nothing.
struct CheckInView: View {
    let kind: CheckInKind

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var measures: [Measure] = []
    @State private var index = 0
    @State private var session: CheckInSession?
    @State private var drafts: [UUID: Entry] = [:]
    @State private var prefillSource: [UUID: String] = [:]
    @State private var answered: [String] = []
    @State private var skipped: [String] = []
    @State private var note = ""
    @State private var durationEdited = false
    @State private var started = false
    @State private var finished = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if measures.isEmpty && started {
                    ContentUnavailableView("Nothing to ask",
                                           systemImage: kind.symbolName,
                                           description: Text("Turn on “\(kind.title)” for measures in the Measures tab."))
                } else if started {
                    progress
                    TabView(selection: $index) {
                        ForEach(Array(measures.enumerated()), id: \.element.id) { i, m in
                            page(m).tag(i)
                        }
                        summary.tag(measures.count)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                    .animation(.snappy, value: index)
                }
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle(kind.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                if index > 0 && index <= measures.count {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { index -= 1 } label: { Image(systemName: "chevron.left") }
                            .accessibilityLabel("Previous question")
                    }
                }
            }
            .sensoryFeedback(.success, trigger: finished)
        }
        .task { await start() }
    }

    // MARK: Pages

    private var progress: some View {
        HStack(spacing: 4) {
            ForEach(0..<max(measures.count, 1), id: \.self) { i in
                Capsule()
                    .fill(i < index ? Color.accentColor : (i == index ? Color.accentColor.opacity(0.6) : Color(uiColor: .tertiarySystemFill)))
                    .frame(height: 4)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private func page(_ m: Measure) -> some View {
        let fields = m.activeFields
        let tint = Palette.color(m.color)
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 10) {
                    MeasureIcon(symbol: m.icon, color: m.color, size: 30)
                    Text(m.name).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                    Spacer()
                    if drafts[m.id]?.revision ?? 0 > 0 {
                        Label("Saved", systemImage: "checkmark.circle.fill").font(.caption).foregroundStyle(.green)
                    }
                }
                if fields.count == 1, let f = fields.first, f.type == .rating {
                    Text(f.displayPrompt).font(.title2.weight(.bold)).fixedSize(horizontal: false, vertical: true)
                    FieldInput(field: f, tint: tint, value: binding(m, f), style: .large) { commit(m) }
                } else if fields.count == 1, let f = fields.first,
                          [.choice, .boolean, .duration].contains(f.type) {
                    Text(f.displayPrompt).font(.title2.weight(.bold)).fixedSize(horizontal: false, vertical: true)
                    FieldInput(field: f, tint: tint, value: binding(m, f)) { commit(m) }
                } else {
                    Text(m.prompt ?? m.name).font(.title2.weight(.bold))
                    if let src = prefillSource[m.id] {
                        Label(src == "healthkit" ? "Pre-filled from Apple Health — check and confirm"
                                                 : "Pre-filled from last time — check and confirm",
                              systemImage: src == "healthkit" ? "heart.text.square" : "clock.arrow.circlepath")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(fields) { f in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(f.displayPrompt).font(.subheadline.weight(.semibold))
                            FieldInput(field: f, tint: tint, value: binding(m, f))
                        }
                        .padding(14)
                        .background(Color(uiColor: .secondarySystemGroupedBackground),
                                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    Button { commit(m) } label: {
                        Text("Confirm").font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(tint)
                    .disabled(!requiredSatisfied(m))
                }
                Button("Skip") { skip(m) }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 4)
                    .foregroundStyle(.secondary)
            }
            .padding()
        }
    }

    private var summary: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(answered.isEmpty ? "All set?" : "Nice work").font(.title2.weight(.bold))
                VStack(spacing: 0) {
                    ForEach(Array(measures.enumerated()), id: \.element.id) { i, m in
                        Button { index = i } label: {
                            HStack {
                                MeasureIcon(symbol: m.icon, color: m.color, size: 26)
                                Text(m.name).foregroundStyle(.primary)
                                Spacer()
                                if let e = drafts[m.id], e.revision > 0 {
                                    Text(ValueText.summary(of: e, measure: m)).font(.caption).foregroundStyle(.secondary)
                                        .lineLimit(1)
                                } else if skipped.contains(m.key) {
                                    Text("Skipped").font(.caption).foregroundStyle(.orange)
                                } else {
                                    Text("—").foregroundStyle(.tertiary)
                                }
                            }
                            .padding(.vertical, 8)
                            .padding(.horizontal, 12)
                        }
                        Divider().padding(.leading, 48)
                    }
                }
                .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                TextField("Anything worth noting? (optional)", text: $note, axis: .vertical)
                    .lineLimit(2...6)
                    .padding(12)
                    .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                Button { finish() } label: {
                    Text("Done").font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent)
            }
            .padding()
        }
    }

    // MARK: Logic

    private func start() async {
        guard !started else { return }
        measures = model.checkInMeasures(kind)
        session = model.startSession(kind, measures: measures)
        note = session?.note ?? ""
        var lastSleep: Entry?
        for m in measures {
            if let existing = model.todayEntry(for: m), m.cardinality == .oncePerDay {
                drafts[m.id] = existing
                if !answered.contains(m.key) { answered.append(m.key) }
            } else {
                drafts[m.id] = model.store.makeEntry(for: m, context: kind.context, sessionID: session?.id)
                if m.key == "sleep_times" { lastSleep = model.store.entries(measureID: m.id, limit: 1).first }
            }
        }
        started = true
        if let sleep = measures.first(where: { $0.key == "sleep_times" }), drafts[sleep.id]?.revision == 0 {
            if model.settings.healthKitSleepPrefill, let s = await HealthSleep.shared.lastNight() {
                prefillSleep(sleep, onset: s.sleepOnset, bed: s.bedtime, wake: s.wakeTime, duration: s.asleepDuration, source: "healthkit")
            } else if let last = lastSleep {
                let cal = Calendar.current
                func shift(_ key: String) -> Date? {
                    guard let d = last.values[key]?.date else { return nil }
                    let c = cal.dateComponents([.hour, .minute], from: d)
                    return SleepMath.lastNight(hour: c.hour ?? 0, minute: c.minute ?? 0, reference: Date())
                }
                prefillSleep(sleep, onset: shift("sleep_onset"), bed: shift("bedtime"), wake: shift("wake_time"),
                             duration: nil, source: "previous")
            }
        }
    }

    private func prefillSleep(_ m: Measure, onset: Date?, bed: Date?, wake: Date?, duration: TimeInterval?, source: String) {
        guard var e = drafts[m.id] else { return }
        if let bed { e.values["bedtime"] = .date(bed) }
        if let onset { e.values["sleep_onset"] = .date(onset) }
        if let wake { e.values["wake_time"] = .date(wake) }
        if let d = duration ?? SleepMath.duration(onset: onset, wake: wake) { e.values["sleep_duration"] = .duration(d) }
        e.metadata["prefill"] = source
        drafts[m.id] = e
        prefillSource[m.id] = source
    }

    private func binding(_ m: Measure, _ f: FieldDefinition) -> Binding<FieldValue?> {
        Binding(get: { drafts[m.id]?.values[f.key] }, set: { newValue in
            guard var e = drafts[m.id] else { return }
            e.values[f.key] = newValue
            if e.metadata["prefill"] != nil { e.metadata["prefill_edited"] = "1" }
            if f.key == "sleep_duration" { durationEdited = true }
            if m.key == "sleep_times", !durationEdited, f.key == "sleep_onset" || f.key == "wake_time",
               let d = SleepMath.duration(onset: e.values["sleep_onset"]?.date, wake: e.values["wake_time"]?.date) {
                e.values["sleep_duration"] = .duration(d)
            }
            drafts[m.id] = e
        })
    }

    private func requiredSatisfied(_ m: Measure) -> Bool {
        guard let e = drafts[m.id] else { return false }
        let fields = m.activeFields
        if fields.allSatisfy({ !$0.isRequired }) { return fields.contains { e.values[$0.key] != nil } }
        return fields.allSatisfy { !$0.isRequired || e.values[$0.key] != nil }
    }

    private func commit(_ m: Measure) {
        guard let draft = drafts[m.id], requiredSatisfied(m) else { return }
        var e = draft
        if e.revision == 0 { e.setOccurredAt(Date()) }
        if let saved = model.save(e) {
            drafts[m.id] = saved
            skipped.removeAll { $0 == m.key }
            if !answered.contains(m.key) { answered.append(m.key) }
            advance(from: m)
        }
    }

    private func skip(_ m: Measure) {
        if drafts[m.id]?.revision == 0, !skipped.contains(m.key) { skipped.append(m.key) }
        advance(from: m)
    }

    private func advance(from m: Measure) {
        guard let i = measures.firstIndex(where: { $0.id == m.id }) else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            withAnimation(.snappy) { index = min(i + 1, measures.count) }
        }
    }

    private func finish() {
        if var s = session {
            s.completedAt = Date()
            s.answeredMeasureKeys = answered
            s.skippedMeasureKeys = skipped.filter { !answered.contains($0) }
            s.presentedMeasureKeys = measures.map(\.key)
            s.note = note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : note
            model.saveSession(s)
        }
        finished = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { dismiss() }
    }
}
