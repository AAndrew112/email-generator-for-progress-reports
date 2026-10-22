import SwiftUI
import LifeLogKit

/// Common, fully-labelled five-point scales.
enum AnchorTemplate: String, CaseIterable, Identifiable {
    case intensity, quality, level, amount, degree, severity, frequency, agreement
    var id: String { rawValue }

    var labels: [String] {
        switch self {
        case .intensity: return Seed.intensity
        case .quality: return Seed.quality
        case .level: return Seed.level
        case .amount: return Seed.amount
        case .degree: return Seed.degree
        case .severity: return Seed.severity
        case .frequency: return ["Never", "Rarely", "Sometimes", "Often", "Always"]
        case .agreement: return ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]
        }
    }

    var title: String { "\(rawValue.capitalized): \(labels.first ?? "") … \(labels.last ?? "")" }
}

struct FieldEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var field: FieldDefinition
    @State private var keyEdited = false
    @State private var newOption = ""
    @State private var quickValuesText = ""
    let isNew: Bool
    let otherKeys: Set<String>
    let onSave: (FieldDefinition) -> Void

    init(field: FieldDefinition, isNew: Bool, otherKeys: Set<String>, onSave: @escaping (FieldDefinition) -> Void) {
        _field = State(initialValue: field)
        self.isNew = isNew
        self.otherKeys = otherKeys
        self.onSave = onSave
        let factor = field.type == .duration ? 60.0 : 1.0
        _quickValuesText = State(initialValue: field.quickValues.map { ValueText.number($0 / factor) }.joined(separator: ", "))
    }

    private var problems: [String] {
        var p: [String] = []
        if field.label.trimmingCharacters(in: .whitespaces).isEmpty { p.append("Add a label.") }
        if field.key.isEmpty { p.append("Add an export key.") }
        if otherKeys.contains(field.key) { p.append("Another field already uses the key “\(field.key)”.") }
        if field.type == .rating {
            let lo = field.minValue ?? 0, hi = field.maxValue ?? 4
            if hi <= lo || hi - lo > 20 { p.append("The scale needs 2–21 points.") }
        }
        if (field.type == .choice || field.type == .multiChoice) && field.activeOptions.isEmpty { p.append("Add at least one option.") }
        return p
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Label (e.g. Intensity)", text: $field.label)
                        .onChange(of: field.label) { _, label in
                            if isNew && !keyEdited { field.key = Slug.unique(Slug.make(label), existing: otherKeys) }
                        }
                    TextField("Question shown when logging (optional)", text: Binding(
                        get: { field.prompt ?? "" }, set: { field.prompt = $0.isEmpty ? nil : $0 }), axis: .vertical)
                    if isNew {
                        Picker("Type", selection: $field.type) {
                            ForEach(FieldType.allCases) { Label($0.displayName, systemImage: $0.symbolName).tag($0) }
                        }
                        .onChange(of: field.type) { _, type in
                            if type == .rating && field.anchors.isEmpty {
                                field.minValue = 0
                                field.maxValue = 4
                                field.anchors = Seed.anchors(Seed.intensity)
                            }
                        }
                    } else {
                        LabeledContent("Type", value: field.type.displayName)
                    }
                    Toggle("Required", isOn: $field.isRequired)
                }

                typeSection

                Section {
                    Picker("In daily.csv", selection: $field.dailyAggregate) {
                        ForEach(DailyAggregate.allCases) { Text($0.displayName).tag($0) }
                    }
                    if isNew {
                        TextField("export_key", text: Binding(get: { field.key }, set: { field.key = Slug.make($0); keyEdited = true }))
                            .font(.body.monospaced())
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    } else {
                        LabeledContent("Export key") { Text(field.key).font(.body.monospaced()) }
                    }
                } header: {
                    Text("Export")
                } footer: {
                    Text("“Automatic” keeps once-per-day answers as-is, totals numbers and durations, and averages ratings.")
                }

                if !problems.isEmpty && !(isNew && field.label.isEmpty) {
                    Section { ForEach(problems, id: \.self) { Text($0).foregroundStyle(.red) } }
                }
            }
            .navigationTitle(isNew ? "New Field" : "Edit Field")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        applyQuickValues()
                        onSave(field)
                        dismiss()
                    }
                    .fontWeight(.semibold)
                    .disabled(!problems.isEmpty)
                }
            }
        }
    }

    @ViewBuilder
    private var typeSection: some View {
        switch field.type {
        case .rating:
            Section {
                Stepper("Lowest: \(Int(field.minValue ?? 0))", value: Binding(
                    get: { Int(field.minValue ?? 0) },
                    set: { field.minValue = Double($0); trimAnchors() }), in: -10...10)
                Stepper("Highest: \(Int(field.maxValue ?? 4))", value: Binding(
                    get: { Int(field.maxValue ?? 4) },
                    set: { field.maxValue = Double($0); trimAnchors() }), in: ((Int(field.minValue ?? 0)) + 1)...((Int(field.minValue ?? 0)) + 20))
                Menu("Use a standard scale…") {
                    ForEach(AnchorTemplate.allCases) { t in
                        Button(t.title) {
                            field.minValue = 0
                            field.maxValue = Double(t.labels.count - 1)
                            field.anchors = Seed.anchors(t.labels)
                        }
                    }
                }
                ForEach(Array(field.ratingRange), id: \.self) { p in
                    HStack {
                        Text("\(p)").font(.body.monospacedDigit().weight(.semibold)).frame(width: 30, alignment: .leading)
                        TextField("Label for \(p)", text: anchorBinding(p))
                    }
                }
            } header: {
                Text("Scale")
            } footer: {
                Text("Label every point (not just the ends) so ratings mean the same thing every day.")
            }
        case .number:
            Section("Number") {
                TextField("Unit (e.g. mg, glasses)", text: Binding(get: { field.unit ?? "" }, set: { field.unit = $0.isEmpty ? nil : $0 }))
                optionalNumber("Minimum", $field.minValue)
                optionalNumber("Maximum", $field.maxValue)
                TextField("One-tap values, e.g. 50, 100, 200", text: $quickValuesText)
                    .keyboardType(.numbersAndPunctuation)
                optionalNumber("Default value", Binding(get: { field.defaultValue?.number },
                                                        set: { field.defaultValue = $0.map(FieldValue.number) }))
            }
        case .duration:
            Section {
                TextField("Minutes, e.g. 5, 15, 30, 60", text: $quickValuesText)
                    .keyboardType(.numbersAndPunctuation)
            } header: {
                Text("One-tap durations (minutes)")
            }
        case .choice, .multiChoice:
            Section {
                ForEach($field.options) { $option in
                    if !option.isArchived {
                        TextField("Option", text: $option.label)
                    }
                }
                .onDelete(perform: deleteOptions)
                .onMove { field.options.move(fromOffsets: $0, toOffset: $1) }
                HStack {
                    TextField("Add option", text: $newOption)
                        .onSubmit(addOption)
                    Button("Add", action: addOption).disabled(newOption.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                if field.type == .choice {
                    Picker("Default", selection: Binding<String?>(
                        get: { field.defaultValue?.choiceKeys.first },
                        set: { field.defaultValue = $0.map { .choices([$0]) } })) {
                        Text("None").tag(String?.none)
                        ForEach(field.activeOptions) { Text($0.label).tag(String?.some($0.key)) }
                    }
                }
                ForEach(field.options.filter(\.isArchived)) { o in
                    HStack {
                        Text(o.label).foregroundStyle(.secondary)
                        Spacer()
                        Button("Restore") {
                            if let i = field.options.firstIndex(where: { $0.key == o.key }) { field.options[i].isArchived = false }
                        }
                        .buttonStyle(.borderless)
                    }
                }
            } header: {
                Text("Options")
            } footer: {
                Text("Renaming an option keeps its data. Removed options are archived, not deleted.")
            }
        case .boolean:
            Section("Default") {
                Picker("Default", selection: Binding<Bool?>(get: { field.defaultValue?.bool },
                                                           set: { field.defaultValue = $0.map(FieldValue.bool) })) {
                    Text("None").tag(Bool?.none)
                    Text("Yes").tag(Bool?.some(true))
                    Text("No").tag(Bool?.some(false))
                }
            }
        case .time, .text, .photo:
            EmptyView()
        }
    }

    private func optionalNumber(_ title: String, _ binding: Binding<Double?>) -> some View {
        HStack {
            Text(title)
            Spacer()
            TextField("—", value: binding, format: .number)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: 120)
        }
    }

    private func anchorBinding(_ p: Int) -> Binding<String> {
        Binding(get: { field.anchorLabel(for: p) ?? "" }, set: { label in
            field.anchors.removeAll { $0.value == p }
            if !label.isEmpty { field.anchors.append(RatingAnchor(value: p, label: label)) }
            field.anchors.sort { $0.value < $1.value }
        })
    }

    private func trimAnchors() {
        let r = field.ratingRange
        field.anchors.removeAll { !r.contains($0.value) }
    }

    private func addOption() {
        let label = newOption.trimmingCharacters(in: .whitespaces)
        guard !label.isEmpty else { return }
        if let i = field.options.firstIndex(where: { $0.label.caseInsensitiveCompare(label) == .orderedSame }) {
            field.options[i].isArchived = false
        } else {
            let key = Slug.unique(Slug.make(label), existing: Set(field.options.map(\.key)))
            field.options.append(ChoiceOption(key: key.isEmpty ? "option" : key, label: label))
        }
        newOption = ""
    }

    private func deleteOptions(at offsets: IndexSet) {
        let keys = offsets.map { field.options[$0].key }
        for k in keys {
            guard let i = field.options.firstIndex(where: { $0.key == k }) else { continue }
            if isNew { field.options.remove(at: i) } else { field.options[i].isArchived = true }
        }
    }

    private func applyQuickValues() {
        guard field.type == .number || field.type == .duration else { return }
        let factor = field.type == .duration ? 60.0 : 1.0
        field.quickValues = quickValuesText
            .split(whereSeparator: { $0 == "," || $0 == " " || $0 == ";" })
            .compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
            .filter { $0 >= 0 }
            .map { $0 * factor }
    }
}

struct PresetEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var preset: Preset
    let measure: Measure
    let onSave: (Preset) -> Void

    init(preset: Preset, measure: Measure, onSave: @escaping (Preset) -> Void) {
        _preset = State(initialValue: preset)
        self.measure = measure
        self.onSave = onSave
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Button label (e.g. Sertraline 50 mg)", text: $preset.label)
                    Toggle("Favorite (one-tap button)", isOn: $preset.isFavorite)
                }
                ForEach(measure.activeFields.filter { $0.type != .photo }) { f in
                    Section(f.displayPrompt) {
                        FieldInput(field: f, tint: Palette.color(measure.color), value: Binding(
                            get: { preset.values[f.key] }, set: { preset.values[f.key] = $0 }))
                    }
                }
            }
            .navigationTitle("Preset")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        preset.values = preset.values.filter { !$0.value.isEmpty }
                        onSave(preset)
                        dismiss()
                    }
                    .fontWeight(.semibold)
                    .disabled(preset.label.trimmingCharacters(in: .whitespaces).isEmpty || preset.values.isEmpty)
                }
            }
        }
    }
}
