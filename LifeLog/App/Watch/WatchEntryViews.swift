import SwiftUI
import WatchKit
import LifeLogKit

/// Fast path for items that need an answer: shows the first missing required
/// question; answering it saves immediately. "More options" opens the full form.
struct WatchEntryFlow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let action: QuickAction
    @State private var entry: Entry

    init(action: QuickAction) {
        self.action = action
        _entry = State(initialValue: StoreFactory.shared.makeEntry(for: action.measure, values: action.values,
                                                                   context: .quickLog, presetID: action.preset?.id))
    }

    private var missing: FieldDefinition? {
        action.measure.activeFields.first { $0.isRequired && entry.values[$0.key] == nil }
    }

    var body: some View {
        NavigationStack {
            if let field = missing {
                WatchFieldPicker(field: field, tint: Palette.color(action.measure.color),
                                 value: Binding(get: { entry.values[field.key] }, set: { entry.values[field.key] = $0 }),
                                 footer: AnyView(NavigationLink("More options") { WatchEntryForm(entry: entry, isNew: true, onSaved: { dismiss() }) })) {
                    if missing == nil { save() }
                }
                .navigationTitle(action.title)
            } else {
                WatchEntryForm(entry: entry, isNew: true, onSaved: { dismiss() })
            }
        }
    }

    private func save() {
        var e = entry
        if let f = action.measure.episodeDurationField, let d = e.values[f.key]?.duration {
            e.setOccurredAt(Date().addingTimeInterval(-d))
        }
        if model.save(e, announce: true) != nil {
            WKInterfaceDevice.current().play(.success)
            dismiss()
        }
    }
}

/// Full entry editor on the Watch: every field, time, delete.
struct WatchEntryForm: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var entry: Entry
    @State private var confirmDelete = false
    let isNew: Bool
    var onSaved: (() -> Void)?

    init(entry: Entry, isNew: Bool, onSaved: (() -> Void)? = nil) {
        _entry = State(initialValue: entry)
        self.isNew = isNew
        self.onSaved = onSaved
    }

    private var measure: Measure? { model.measure(entry.measureID) }

    private var canSave: Bool {
        (measure?.activeFields ?? []).allSatisfy { !$0.isRequired || entry.values[$0.key] != nil }
    }

    var body: some View {
        List {
            ForEach((measure?.activeFields ?? []).filter { $0.type != .photo }) { f in
                NavigationLink {
                    WatchFieldPicker(field: f, tint: Palette.color(measure?.color ?? "blue"),
                                     value: Binding(get: { entry.values[f.key] }, set: { entry.values[f.key] = $0 }))
                } label: {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(f.label).font(.caption).foregroundStyle(.secondary)
                        Text(entry.values[f.key].map { ValueText.display($0, field: f, timeZone: entry.timeZone) } ?? "—")
                            .font(.body)
                            .lineLimit(2)
                    }
                }
            }
            Section {
                DatePicker(measure?.timing == .episode ? "Started" : "Time",
                           selection: Binding(get: { entry.occurredAt }, set: { entry.setOccurredAt($0) }),
                           displayedComponents: [.date, .hourAndMinute])
            }
            Section {
                Button(isNew ? "Save" : "Save Changes") { save() }
                    .disabled(!canSave)
                    .foregroundStyle(canSave ? Color.accentColor : .secondary)
                if !isNew {
                    Button("Delete", role: .destructive) { confirmDelete = true }
                }
            }
        }
        .navigationTitle(measure?.name ?? "Entry")
        .confirmationDialog("Delete this entry?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) {
                model.delete(entry.id)
                dismiss()
            }
        }
    }

    private func save() {
        guard model.save(entry, announce: isNew) != nil else { return }
        WKInterfaceDevice.current().play(.success)
        if let onSaved { onSaved() } else { dismiss() }
    }
}

/// Picks one field's value with large tap targets. Calls `onAnswered` after a discrete answer.
struct WatchFieldPicker: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?
    var footer: AnyView? = nil
    var onAnswered: (() -> Void)? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var number: Double = 0
    @State private var date = Date()
    @State private var text = ""

    init(field: FieldDefinition, tint: Color, value: Binding<FieldValue?>, footer: AnyView? = nil,
         onAnswered: (() -> Void)? = nil) {
        self.field = field
        self.tint = tint
        _value = value
        self.footer = footer
        self.onAnswered = onAnswered
    }

    var body: some View {
        List {
            Section {
                content
            } header: {
                Text(field.displayPrompt).font(.footnote).textCase(nil)
            }
            if let footer { Section { footer } }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch field.type {
        case .rating:
            ForEach(Array(field.ratingRange), id: \.self) { p in
                optionButton(title: field.anchorLabel(for: p).map { "\(p)  \($0)" } ?? "\(p)",
                             selected: value?.number == Double(p)) { value = .number(Double(p)) }
            }
        case .choice:
            ForEach(field.activeOptions) { o in
                optionButton(title: o.label, selected: value?.choiceKeys == [o.key]) { value = .choices([o.key]) }
            }
        case .multiChoice:
            ForEach(field.activeOptions) { o in
                let selected = value?.choiceKeys.contains(o.key) == true
                Button {
                    var keys = value?.choiceKeys ?? []
                    if selected { keys.removeAll { $0 == o.key } } else { keys.append(o.key) }
                    value = keys.isEmpty ? nil : .choices(keys)
                } label: {
                    HStack {
                        Text(o.label)
                        Spacer()
                        Image(systemName: selected ? "checkmark.circle.fill" : "circle").foregroundStyle(selected ? tint : .secondary)
                    }
                }
            }
            doneButton
        case .boolean:
            optionButton(title: "Yes", selected: value?.bool == true) { value = .bool(true) }
            optionButton(title: "No", selected: value?.bool == false) { value = .bool(false) }
        case .duration:
            let quick = field.quickValues.isEmpty ? [5, 10, 15, 30, 60, 90].map { Double($0 * 60) } : field.quickValues
            ForEach(quick, id: \.self) { q in
                optionButton(title: ValueText.duration(q), selected: value?.duration == q) { value = .duration(q) }
            }
            Stepper(value: $number, in: 0...1440, step: 5) {
                Text(number > 0 ? ValueText.duration(number * 60) : "Custom").font(.footnote)
            }
            .onAppear { number = (value?.duration ?? 0) / 60 }
            if number > 0 && value?.duration != number * 60 {
                Button("Use \(ValueText.duration(number * 60))") { value = .duration(number * 60); answered() }
            }
        case .number:
            if !field.quickValues.isEmpty {
                ForEach(field.quickValues, id: \.self) { q in
                    optionButton(title: ValueText.number(q) + (field.unit.map { " \($0)" } ?? ""),
                                 selected: value?.number == q) { value = .number(q) }
                }
            }
            Stepper(value: $number, in: (field.minValue ?? 0)...(field.maxValue ?? 100_000), step: field.step ?? 1) {
                Text(ValueText.number(number) + (field.unit.map { " \($0)" } ?? "")).font(.title3.monospacedDigit())
            }
            .onAppear { number = value?.number ?? field.minValue ?? 0 }
            Button("Use \(ValueText.number(number))") { value = .number(number); answered() }
        case .time:
            DatePicker("Time", selection: $date, displayedComponents: [.hourAndMinute])
                .onAppear { date = value?.date ?? Date() }
            Button("Set") { value = .date(date); answered() }
        case .text:
            TextField(field.label, text: $text)
                .onAppear { text = value?.text ?? "" }
            Button("Done") { value = text.isEmpty ? nil : .text(text); answered() }
        case .photo:
            Text("Add photos from your iPhone.").font(.footnote).foregroundStyle(.secondary)
        }
        if value != nil && field.type != .multiChoice {
            Button("Clear", role: .destructive) { value = nil }
                .font(.footnote)
        }
    }

    private var doneButton: some View {
        Button("Done") { answered() }.foregroundStyle(tint)
    }

    private func optionButton(title: String, selected: Bool, set: @escaping () -> Void) -> some View {
        Button {
            set()
            WKInterfaceDevice.current().play(.click)
            answered()
        } label: {
            HStack {
                Text(title).font(.body.weight(selected ? .semibold : .regular))
                Spacer()
                if selected { Image(systemName: "checkmark").foregroundStyle(tint) }
            }
        }
        .listItemTint(selected ? tint : nil)
    }

    private func answered() {
        if let onAnswered { onAnswered() } else { dismiss() }
    }
}
