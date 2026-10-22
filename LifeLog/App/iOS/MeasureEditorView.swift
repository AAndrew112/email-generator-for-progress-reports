import SwiftUI
import LifeLogKit

struct MeasureEditorView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var draft: Measure
    @State private var keyEdited = false
    @State private var fieldItem: FieldItem?
    @State private var presetItem: PresetItem?
    @State private var confirmDelete = false
    let isNew: Bool

    struct FieldItem: Identifiable {
        let id = UUID()
        let field: FieldDefinition
        let isNew: Bool
    }

    struct PresetItem: Identifiable {
        let id = UUID()
        let preset: Preset
        let isNew: Bool
    }

    init(measure: Measure, isNew: Bool) {
        _draft = State(initialValue: measure)
        self.isNew = isNew
    }

    private var errors: [MeasureValidationError] {
        var d = draft
        if isNew && d.key.isEmpty { d.key = Slug.make(d.name) }
        if d.key.isEmpty && isNew { return d.name.isEmpty ? [.emptyName] : [.invalidKey] }
        return d.validate(existingKeys: model.existingKeys())
    }

    private var tint: Color { Palette.color(draft.color) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 12) {
                        MeasureIcon(symbol: draft.icon, color: draft.color, size: 44)
                        TextField("Name", text: $draft.name)
                            .font(.title3.weight(.semibold))
                            .onChange(of: draft.name) { _, name in
                                if isNew && !keyEdited { draft.key = Slug.make(name) }
                            }
                    }
                    TextField("Description or question (optional)", text: optional($draft.prompt), axis: .vertical)
                        .lineLimit(1...4)
                }

                Section("Appearance") {
                    NavigationLink {
                        IconPicker(symbol: $draft.icon, color: draft.color)
                    } label: {
                        LabeledContent("Icon") { Image(systemName: draft.icon).foregroundStyle(tint) }
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 10) {
                            ForEach(Palette.names, id: \.self) { name in
                                Circle()
                                    .fill(Palette.color(name).gradient)
                                    .frame(width: 28, height: 28)
                                    .overlay { if name == draft.color { Image(systemName: "checkmark").font(.caption.bold()).foregroundStyle(.white) } }
                                    .onTapGesture { draft.color = name }
                                    .accessibilityLabel(name)
                                    .accessibilityAddTraits(name == draft.color ? .isSelected : [])
                            }
                        }
                        .padding(.vertical, 4)
                    }
                    HStack {
                        TextField("Group", text: $draft.group)
                        Menu {
                            ForEach(model.groups, id: \.self) { g in Button(g) { draft.group = g } }
                        } label: {
                            Image(systemName: "chevron.up.chevron.down")
                        }
                    }
                }

                Section {
                    Toggle(isOn: $draft.inMorningCheckIn) { Label("Morning check-in", systemImage: "sunrise") }
                    Toggle(isOn: $draft.inEveningCheckIn) { Label("Evening check-in", systemImage: "moon.stars") }
                    Toggle(isOn: $draft.inQuickLog) { Label("Quick log", systemImage: "bolt") }
                    Toggle(isOn: $draft.isFavorite) { Label("Favorite (Today screen, widget, Watch)", systemImage: "star") }
                    Picker("How often", selection: $draft.cardinality) {
                        ForEach(Cardinality.allCases) { Text($0.displayName).tag($0) }
                    }
                    if draft.activeFields.contains(where: { $0.type == .duration }) {
                        Toggle("Time marks the start of an episode", isOn: Binding(
                            get: { draft.timing == .episode }, set: { draft.timing = $0 ? .episode : .point }))
                    }
                } header: {
                    Text("Logging")
                } footer: {
                    Text(draft.cardinality == .oncePerDay
                         ? "One answer per day. Answering again updates that day’s entry."
                         : "Log as often as it happens; each entry gets its own timestamp.")
                }

                fieldsSection

                if draft.fields.contains(where: \.isArchived) {
                    Section {
                        ForEach(draft.fields.filter(\.isArchived)) { f in
                            HStack {
                                Label(f.label, systemImage: f.type.symbolName).foregroundStyle(.secondary)
                                Spacer()
                                Button("Restore") { setArchived(f.id, false) }.buttonStyle(.borderless)
                            }
                        }
                    } header: {
                        Text("Archived fields")
                    } footer: {
                        Text("Archived fields are hidden when logging but kept so older data stays interpretable.")
                    }
                }

                presetsSection

                Section {
                    if isNew {
                        TextField("export_key", text: Binding(get: { draft.key }, set: { draft.key = Slug.make($0); keyEdited = true }))
                            .font(.body.monospaced())
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    } else {
                        LabeledContent("Key") { Text(draft.key).font(.body.monospaced()) }
                    }
                } header: {
                    Text("Export key")
                } footer: {
                    Text("Used as the column name in CSV exports. It can’t change after saving, so renaming the measure never breaks your data.")
                }

                if !isNew {
                    Section {
                        Toggle("Active", isOn: $draft.isActive)
                        Button("Delete Measure", role: .destructive) { confirmDelete = true }
                    } footer: {
                        Text("Inactive measures are hidden from logging but keep their history.")
                    }
                }

                if !errors.isEmpty && !(isNew && draft.name.isEmpty) {
                    Section {
                        ForEach(errors.map(\.description), id: \.self) { Text($0).foregroundStyle(.red) }
                    }
                }
            }
            .navigationTitle(isNew ? "New Measure" : "Edit Measure")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }.fontWeight(.semibold).disabled(!errors.isEmpty)
                }
            }
            .sheet(item: $fieldItem) { item in
                FieldEditorView(field: item.field, isNew: item.isNew,
                                otherKeys: Set(draft.fields.filter { $0.id != item.field.id }.map(\.key))) { saved in
                    if let i = draft.fields.firstIndex(where: { $0.id == saved.id }) {
                        draft.fields[i] = saved
                    } else {
                        draft.fields.append(saved)
                    }
                }
            }
            .sheet(item: $presetItem) { item in
                PresetEditorView(preset: item.preset, measure: draft) { saved in
                    if let i = draft.presets.firstIndex(where: { $0.id == saved.id }) {
                        draft.presets[i] = saved
                    } else {
                        draft.presets.append(saved)
                    }
                }
            }
            .confirmationDialog("Delete “\(draft.name)”?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete Measure", role: .destructive) {
                    model.deleteMeasure(draft.id)
                    dismiss()
                }
            } message: {
                Text("Existing entries are kept and still exported.")
            }
        }
    }

    private var fieldsSection: some View {
        Section {
            ForEach(draft.activeFields) { f in
                Button { fieldItem = FieldItem(field: f, isNew: false) } label: {
                    HStack {
                        Image(systemName: f.type.symbolName).foregroundStyle(tint).frame(width: 24)
                        VStack(alignment: .leading) {
                            Text(f.label).foregroundStyle(.primary)
                            Text(fieldSummary(f)).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if f.isRequired { Text("Required").font(.caption2).foregroundStyle(.secondary) }
                    }
                }
            }
            .onMove(perform: moveFields)
            .onDelete(perform: deleteFields)
            Menu {
                ForEach(FieldType.allCases) { type in
                    Button { fieldItem = FieldItem(field: newField(type), isNew: true) } label: {
                        Label(type.displayName, systemImage: type.symbolName)
                    }
                }
            } label: {
                Label("Add Field", systemImage: "plus.circle.fill")
            }
        } header: {
            Text("Fields")
        } footer: {
            Text("The first field is the main question. Required fields must be answered; everything else is optional.")
        }
    }

    private var presetsSection: some View {
        Section {
            ForEach(draft.presets) { p in
                HStack {
                    Button { presetItem = PresetItem(preset: p, isNew: false) } label: {
                        VStack(alignment: .leading) {
                            Text(p.label).foregroundStyle(.primary)
                            Text(ValueText.summary(of: Entry(measureID: draft.id, measureKey: draft.key, occurredAt: Date(), values: p.values),
                                                   measure: draft))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Button {
                        if let i = draft.presets.firstIndex(where: { $0.id == p.id }) { draft.presets[i].isFavorite.toggle() }
                    } label: {
                        Image(systemName: p.isFavorite ? "star.fill" : "star").foregroundStyle(.yellow)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(p.isFavorite ? "Unstar preset" : "Star preset")
                }
            }
            .onDelete { draft.presets.remove(atOffsets: $0) }
            .onMove { draft.presets.move(fromOffsets: $0, toOffset: $1) }
            Button {
                presetItem = PresetItem(preset: Preset(label: "", values: [:]), isNew: true)
            } label: {
                Label("Add Preset", systemImage: "plus.circle.fill")
            }
            .disabled(draft.activeFields.isEmpty)
        } header: {
            Text("Presets")
        } footer: {
            Text("Presets are saved answers, like “Coffee · 95 mg” or a regular medication and dose. Starred presets become one-tap buttons.")
        }
    }

    // MARK: Helpers

    private func optional(_ binding: Binding<String?>) -> Binding<String> {
        Binding(get: { binding.wrappedValue ?? "" }, set: { binding.wrappedValue = $0.isEmpty ? nil : $0 })
    }

    private func fieldSummary(_ f: FieldDefinition) -> String {
        switch f.type {
        case .rating:
            let r = f.ratingRange
            return "\(r.lowerBound)–\(r.upperBound): \(f.anchorLabel(for: r.lowerBound) ?? "") → \(f.anchorLabel(for: r.upperBound) ?? "")"
        case .number: return f.unit.map { "Number (\($0))" } ?? "Number"
        case .choice, .multiChoice: return "\(f.type.displayName): " + f.activeOptions.map(\.label).joined(separator: ", ")
        default: return f.type.displayName
        }
    }

    private func newField(_ type: FieldType) -> FieldDefinition {
        var f = FieldDefinition(key: "", label: "", type: type)
        switch type {
        case .rating:
            f.minValue = 0
            f.maxValue = 4
            f.step = 1
            f.anchors = Seed.anchors(Seed.intensity)
        case .duration:
            f.quickValues = [5, 10, 15, 30, 60].map { Double($0 * 60) }
        case .choice, .multiChoice:
            f.options = []
        default:
            break
        }
        return f
    }

    private func moveFields(from: IndexSet, to: Int) {
        var active = draft.activeFields
        active.move(fromOffsets: from, toOffset: to)
        draft.fields = active + draft.fields.filter(\.isArchived)
    }

    private func deleteFields(at offsets: IndexSet) {
        let ids = offsets.map { draft.activeFields[$0].id }
        let saved = model.store.measure(id: draft.id)
        for id in ids {
            if saved?.fields.contains(where: { $0.id == id }) == true {
                setArchived(id, true)
            } else {
                draft.fields.removeAll { $0.id == id }
            }
        }
    }

    private func setArchived(_ id: UUID, _ archived: Bool) {
        guard let i = draft.fields.firstIndex(where: { $0.id == id }) else { return }
        draft.fields[i].isArchived = archived
    }

    private func save() {
        var m = draft
        m.name = m.name.trimmingCharacters(in: .whitespaces)
        m.group = m.group.trimmingCharacters(in: .whitespaces).isEmpty ? "Custom" : m.group.trimmingCharacters(in: .whitespaces)
        if m.timing == .episode && !m.activeFields.contains(where: { $0.type == .duration }) { m.timing = .point }
        if isNew && m.key.isEmpty { m.key = Slug.make(m.name) }
        if model.saveMeasure(m) != nil { dismiss() }
    }
}

struct IconPicker: View {
    @Binding var symbol: String
    let color: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 52), spacing: 12)], spacing: 12) {
                ForEach(SymbolCatalog.symbols, id: \.self) { s in
                    Button {
                        symbol = s
                        dismiss()
                    } label: {
                        MeasureIcon(symbol: s, color: s == symbol ? color : "gray", size: 46)
                    }
                    .accessibilityLabel(s)
                }
            }
            .padding()
        }
        .navigationTitle("Icon")
    }
}
