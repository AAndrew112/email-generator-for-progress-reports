import SwiftUI
import LifeLogKit

/// Add, edit, reorder, star, deactivate and delete measures.
struct MeasuresView: View {
    @Environment(AppModel.self) private var model
    @State private var editorItem: EditorItem?
    @State private var pendingDelete: Measure?

    struct EditorItem: Identifiable {
        let id = UUID()
        let measure: Measure
        let isNew: Bool
    }

    private func measures(in group: String) -> [Measure] { model.measures.filter { $0.group == group } }

    var body: some View {
        NavigationStack {
            List {
                ForEach(model.groups.filter { !measures(in: $0).isEmpty }, id: \.self) { group in
                    Section(group) {
                        ForEach(measures(in: group)) { m in
                            Button { editorItem = EditorItem(measure: m, isNew: false) } label: { row(m) }
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) { pendingDelete = m } label: { Label("Delete", systemImage: "trash") }
                                    Button {
                                        var c = m
                                        c.isActive.toggle()
                                        model.saveMeasure(c)
                                    } label: {
                                        Label(m.isActive ? "Deactivate" : "Activate", systemImage: m.isActive ? "pause.circle" : "play.circle")
                                    }
                                    .tint(m.isActive ? .orange : .green)
                                }
                                .swipeActions(edge: .leading) {
                                    Button {
                                        var c = m
                                        c.isFavorite.toggle()
                                        model.saveMeasure(c)
                                    } label: {
                                        Label(m.isFavorite ? "Unstar" : "Star", systemImage: m.isFavorite ? "star.slash" : "star")
                                    }
                                    .tint(.yellow)
                                }
                        }
                        .onMove { from, to in move(group: group, from: from, to: to) }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Measures")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { EditButton() }
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        ForEach(MeasureTemplate.allCases) { t in
                            Button { editorItem = EditorItem(measure: t.make(), isNew: true) } label: {
                                Label(t.title, systemImage: t.symbol)
                            }
                        }
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("New measure")
                }
            }
            .sheet(item: $editorItem) { item in
                MeasureEditorView(measure: item.measure, isNew: item.isNew).environment(model)
            }
            .confirmationDialog("Delete “\(pendingDelete?.name ?? "")”?", isPresented: Binding(
                get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }), titleVisibility: .visible) {
                Button("Delete Measure", role: .destructive) {
                    if let m = pendingDelete { model.deleteMeasure(m.id) }
                    pendingDelete = nil
                }
            } message: {
                Text("It disappears from logging. Entries already recorded, and the definition needed to interpret them, are kept and still exported. To pause instead, deactivate it.")
            }
        }
    }

    private func row(_ m: Measure) -> some View {
        HStack(spacing: 12) {
            MeasureIcon(symbol: m.icon, color: m.color, size: 32)
                .opacity(m.isActive ? 1 : 0.4)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(m.name).foregroundStyle(m.isActive ? .primary : .secondary)
                    if m.isFavorite || m.presets.contains(where: \.isFavorite) {
                        Image(systemName: "star.fill").font(.caption2).foregroundStyle(.yellow)
                    }
                }
                Text(placements(m)).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func placements(_ m: Measure) -> String {
        guard m.isActive else { return "Inactive" }
        var parts: [String] = []
        if m.inMorningCheckIn { parts.append("Morning") }
        if m.inEveningCheckIn { parts.append("Evening") }
        if m.inQuickLog { parts.append("Quick log") }
        let fields = m.activeFields.count
        parts.append(fields == 1 ? m.activeFields[0].type.displayName : "\(fields) fields")
        return parts.joined(separator: " · ")
    }

    private func move(group: String, from: IndexSet, to: Int) {
        var lists = model.groups.map { ($0, measures(in: $0)) }
        guard let gi = lists.firstIndex(where: { $0.0 == group }) else { return }
        lists[gi].1.move(fromOffsets: from, toOffset: to)
        // Deleted/hidden measures keep their place at the end.
        let visible = lists.flatMap { $0.1.map(\.id) }
        model.reorder(visible)
    }
}

/// Starting points for new measures.
enum MeasureTemplate: String, CaseIterable, Identifiable {
    case rating, event, yesNo, number, duration, choice, time, text, blank
    var id: String { rawValue }

    var title: String {
        switch self {
        case .rating: return "Rating (0–4)"
        case .event: return "Event (one tap)"
        case .yesNo: return "Yes / No"
        case .number: return "Number"
        case .duration: return "Duration"
        case .choice: return "Choice"
        case .time: return "Time of day"
        case .text: return "Text"
        case .blank: return "Blank"
        }
    }

    var symbol: String {
        switch self {
        case .rating: return FieldType.rating.symbolName
        case .event: return "hand.tap"
        case .yesNo: return FieldType.boolean.symbolName
        case .number: return FieldType.number.symbolName
        case .duration: return FieldType.duration.symbolName
        case .choice: return FieldType.choice.symbolName
        case .time: return FieldType.time.symbolName
        case .text: return FieldType.text.symbolName
        case .blank: return "square.dashed"
        }
    }

    func make() -> Measure {
        var fields: [FieldDefinition] = []
        var cardinality = Cardinality.multiple
        var icon = "circle.fill"
        switch self {
        case .rating:
            fields = [FieldDefinition(key: "rating", label: "Rating", type: .rating, minValue: 0, maxValue: 4, step: 1,
                                      anchors: Seed.anchors(Seed.intensity), isRequired: true)]
            cardinality = .oncePerDay
            icon = "dial.medium"
        case .event:
            fields = [FieldDefinition(key: "intensity", label: "Intensity", type: .rating, minValue: 0, maxValue: 4,
                                      step: 1, anchors: Seed.anchors(Seed.intensity))]
            icon = "hand.tap.fill"
        case .yesNo:
            fields = [FieldDefinition(key: "answer", label: "Answer", type: .boolean, isRequired: true)]
            cardinality = .oncePerDay
            icon = "checkmark.circle.fill"
        case .number:
            fields = [FieldDefinition(key: "amount", label: "Amount", type: .number, isRequired: true)]
            icon = "number"
        case .duration:
            fields = [FieldDefinition(key: "duration", label: "Duration", type: .duration, isRequired: true,
                                      quickValues: [5, 10, 15, 30, 60, 90].map { Double($0 * 60) })]
            icon = "timer"
        case .choice:
            fields = [FieldDefinition(key: "choice", label: "Choice", type: .choice,
                                      options: [ChoiceOption("Option A"), ChoiceOption("Option B")], isRequired: true)]
            icon = "list.bullet.circle.fill"
        case .time:
            fields = [FieldDefinition(key: "time", label: "Time", type: .time, isRequired: true)]
            cardinality = .oncePerDay
            icon = "clock.fill"
        case .text:
            fields = [FieldDefinition(key: "text", label: "Text", type: .text, isRequired: true)]
            icon = "text.alignleft"
        case .blank:
            break
        }
        return Measure(key: "", name: "", group: "Custom", icon: icon, color: "blue", fields: fields,
                       cardinality: cardinality, inQuickLog: true, isFavorite: false, sortOrder: 100_000,
                       createdAt: Date(), modifiedAt: Date())
    }
}
