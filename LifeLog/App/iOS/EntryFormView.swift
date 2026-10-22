import SwiftUI
import LifeLogKit

/// Creates or edits an entry. In `quick` mode (from a quick-log tile) answering
/// the required question saves immediately, so most events take two taps.
struct EntryFormView: View {
    enum Mode {
        case new(QuickAction, context: EntryContext, at: Date?)
        case edit(Entry)
    }

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    let isNew: Bool
    let quick: Bool
    @State private var entry: Entry
    @State private var touchedOptional = false
    @State private var timeEdited = false
    @State private var confirmDelete = false
    private let original: Entry?

    init(mode: Mode, quick: Bool = false) {
        switch mode {
        case .new(let action, let context, let at):
            var e = StoreFactory.shared.makeEntry(for: action.measure, values: action.values, occurredAt: at,
                                                  context: context, presetID: action.preset?.id)
            if at != nil { e.context = .manual }
            _entry = State(initialValue: e)
            isNew = true
            original = nil
            _timeEdited = State(initialValue: at != nil)
        case .edit(let e):
            _entry = State(initialValue: e)
            isNew = false
            original = e
        }
        self.quick = quick
    }

    private var measure: Measure? { model.measure(entry.measureID) }
    private var tint: Color { Palette.color(measure?.color ?? "blue") }

    private var orderedFields: [FieldDefinition] {
        guard let m = measure else { return [] }
        var fields = m.activeFields
        // Archived fields stay visible when this entry has a value for them.
        fields += m.fields.filter { $0.isArchived && entry.values[$0.key] != nil }
        if quick { fields = fields.filter(\.isRequired) + fields.filter { !$0.isRequired } }
        return fields
    }

    private var missingRequired: [FieldDefinition] {
        (measure?.activeFields ?? []).filter { $0.isRequired && entry.values[$0.key] == nil }
    }

    var body: some View {
        NavigationStack {
            Form {
                header
                ForEach(orderedFields) { field in
                    Section {
                        FieldInput(field: field, tint: tint, value: binding(for: field),
                                   suggestions: field.type == .text ? model.store.recentTextValues(measureID: entry.measureID, fieldKey: field.key) : [],
                                   onAnswered: { answered(field) })
                    } header: {
                        HStack {
                            Text(field.displayPrompt)
                            if field.isRequired { Text("· required").foregroundStyle(.tertiary) }
                            if field.isArchived { Text("· archived").foregroundStyle(.tertiary) }
                        }
                    }
                }
                timeSection
                Section("Note") {
                    TextField("Optional", text: Binding(get: { entry.note ?? "" }, set: { entry.note = $0.isEmpty ? nil : $0 }),
                              axis: .vertical)
                        .lineLimit(1...6)
                }
                if !isNew { historySection }
            }
            .navigationTitle(isNew ? (measure?.name ?? "New Entry") : "Edit Entry")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }
                        .fontWeight(.semibold)
                        .disabled(!missingRequired.isEmpty || (!isNew && entry == original))
                }
            }
            .confirmationDialog("Delete this entry?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) {
                    model.delete(entry.id)
                    dismiss()
                }
            } message: {
                Text("It will be removed from exports. You can restore it from History → Recently Deleted.")
            }
        }
    }

    private var header: some View {
        Section {
            HStack(spacing: 12) {
                MeasureIcon(symbol: measure?.icon ?? "circle", color: measure?.color ?? "blue", size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text(measure?.name ?? entry.measureKey).font(.headline)
                    if let p = measure?.prompt, !p.isEmpty {
                        Text(p).font(.caption).foregroundStyle(.secondary)
                    }
                    if quick && !missingRequired.isEmpty {
                        Text("Tap an answer to save").font(.caption2.weight(.medium)).foregroundStyle(tint)
                    }
                }
            }
        }
    }

    private var isEpisode: Bool { measure?.timing == .episode }

    private var timeSection: some View {
        Section {
            DatePicker(isEpisode ? "Started" : "Time",
                       selection: Binding(get: { entry.occurredAt }, set: { setTime($0) }),
                       in: ...Date().addingTimeInterval(24 * 3600))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach([0, 5, 15, 30, 60, 120], id: \.self) { minutes in
                        Chip(title: minutes == 0 ? "Now" : (minutes < 60 ? "−\(minutes)m" : "−\(minutes / 60)h"),
                             isSelected: false, tint: tint) {
                            setTime(Date().addingTimeInterval(-Double(minutes) * 60 - episodeLength))
                        }
                    }
                }
            }
        } header: {
            Text("When")
        } footer: {
            if isEpisode, let end = entry.endedAt(for: measure) {
                Text("Ended \(end.formatted(date: .omitted, time: .shortened)). Start time is when the episode began.")
            } else if entry.timeZoneID != TimeZone.current.identifier {
                Text("Recorded in \(entry.timeZoneID).")
            }
        }
    }

    private var episodeLength: TimeInterval {
        guard let f = measure?.episodeDurationField else { return 0 }
        return entry.values[f.key]?.duration ?? 0
    }

    private var historySection: some View {
        Section("Record") {
            LabeledContent("Logged", value: "\(entry.createdAt.formatted(date: .abbreviated, time: .shortened)) · \(entry.source.label)")
            if entry.revision > 1 {
                NavigationLink {
                    EntryHistoryView(entryID: entry.id)
                } label: {
                    LabeledContent("Edits", value: "\(entry.revision - 1)")
                }
            }
            Button("Delete Entry", role: .destructive) { confirmDelete = true }
        }
    }

    private func binding(for field: FieldDefinition) -> Binding<FieldValue?> {
        Binding(get: { entry.values[field.key] }, set: { newValue in
            entry.values[field.key] = newValue
            if !field.isRequired { touchedOptional = true }
            if isNew && isEpisode && !timeEdited && field.type == .duration {
                // "Ended now": keep the start consistent with the chosen length.
                entry.setOccurredAt(Date().addingTimeInterval(-(newValue?.duration ?? 0)))
            }
        })
    }

    private func setTime(_ date: Date) {
        timeEdited = true
        entry.setOccurredAt(date)
    }

    private func answered(_ field: FieldDefinition) {
        guard quick, isNew, field.isRequired, !touchedOptional else { return }
        // Let the selection animate before closing.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            if missingRequired.isEmpty { save() }
        }
    }

    private func save() {
        if model.save(entry, announce: isNew) != nil { dismiss() }
    }
}

extension EntrySource {
    var label: String {
        switch self {
        case .iPhone: return "iPhone"
        case .watch: return "Apple Watch"
        case .widget: return "Widget"
        case .healthKit: return "Apple Health"
        case .importFile: return "Import"
        case .other: return "Other"
        }
    }
}

/// Every saved version of an entry, newest first.
struct EntryHistoryView: View {
    @Environment(AppModel.self) private var model
    let entryID: UUID

    var body: some View {
        let revisions = model.store.entryRevisions(entryID: entryID).reversed()
        List {
            ForEach(Array(revisions.enumerated()), id: \.offset) { _, r in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Version \(r.revision)").font(.subheadline.weight(.semibold))
                        Text(r.changeKind.rawValue.capitalized).font(.caption)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Color(uiColor: .tertiarySystemFill), in: Capsule())
                        Spacer()
                        Text(r.changedAt.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary)
                    }
                    Text(ValueText.summary(of: r.snapshot, measure: model.measure(r.snapshot.measureID)))
                        .font(.callout)
                    Text("Time: \(r.snapshot.occurredAt.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption).foregroundStyle(.secondary)
                    if let n = r.snapshot.note { Text("Note: \(n)").font(.caption).foregroundStyle(.secondary) }
                }
                .padding(.vertical, 2)
            }
        }
        .navigationTitle("Edit History")
    }
}
