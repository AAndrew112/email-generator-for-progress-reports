import SwiftUI
import LifeLogKit

/// All entries, newest first, grouped by logical day. Tap to edit, swipe to delete.
struct HistoryView: View {
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router
    @State private var entries: [Entry] = []
    @State private var limit = 300
    @State private var search = ""
    @State private var measureFilter: UUID?

    private var filtered: [Entry] {
        entries.filter { e in
            if let f = measureFilter, e.measureID != f { return false }
            guard !search.isEmpty else { return true }
            let m = model.measure(e.measureID)
            return (m?.name ?? e.measureKey).localizedCaseInsensitiveContains(search)
                || ValueText.summary(of: e, measure: m).localizedCaseInsensitiveContains(search)
                || (e.note ?? "").localizedCaseInsensitiveContains(search)
        }
    }

    private var days: [(String, [Entry])] {
        let grouped = Dictionary(grouping: filtered, by: \.dayKey)
        return grouped.keys.sorted(by: >).map { ($0, grouped[$0] ?? []) }
    }

    var body: some View {
        NavigationStack {
            List {
                if entries.isEmpty {
                    ContentUnavailableView("No entries yet", systemImage: "tray",
                                           description: Text("Everything you log appears here."))
                }
                ForEach(days, id: \.0) { day, items in
                    Section {
                        ForEach(items) { entry in
                            EntryRow(entry: entry, measure: model.measure(entry.measureID))
                                .contentShape(Rectangle())
                                .onTapGesture { router.sheet = .editEntry(entry.id) }
                                .swipeActions {
                                    Button(role: .destructive) { model.delete(entry.id) } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                        }
                    } header: {
                        dayHeader(day, count: items.count)
                    }
                }
                if entries.count >= limit {
                    Button("Load more") {
                        limit += 500
                        load()
                    }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $search, prompt: "Search entries and notes")
            .navigationTitle("History")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Picker("Measure", selection: $measureFilter) {
                            Text("All measures").tag(UUID?.none)
                            ForEach(model.store.measures(includeDeleted: true)) { m in
                                Text(m.name).tag(UUID?.some(m.id))
                            }
                        }
                    } label: {
                        Image(systemName: measureFilter == nil ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
                    }
                    .accessibilityLabel("Filter")
                }
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button { router.sheet = .pickMeasure } label: { Label("Add past entry", systemImage: "plus") }
                        NavigationLink { DeletedEntriesView() } label: { Label("Recently deleted", systemImage: "trash") }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .onAppear(perform: load)
            .onChange(of: model.revision) { _, _ in load() }
        }
    }

    private func dayHeader(_ day: String, count: Int) -> some View {
        HStack {
            Text(dayTitle(day))
            if let s = model.settings.study(containing: day) {
                Text("· Day \(s.1)").foregroundStyle(.tint)
            }
            Spacer()
            Text("\(count)").monospacedDigit()
        }
    }

    private func dayTitle(_ key: String) -> String {
        if key == model.todayKey { return "Today" }
        if key == DayKey.adding(days: -1, to: model.todayKey) { return "Yesterday" }
        guard let p = DayKey.parse(key),
              let date = Calendar.current.date(from: DateComponents(year: p.year, month: p.month, day: p.day)) else { return key }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }

    private func load() {
        entries = model.store.recentEntries(limit: limit)
    }
}

struct DeletedEntriesView: View {
    @Environment(AppModel.self) private var model
    @State private var entries: [Entry] = []

    var body: some View {
        List {
            if entries.isEmpty {
                ContentUnavailableView("Nothing deleted", systemImage: "trash.slash")
            }
            ForEach(entries) { entry in
                EntryRow(entry: entry, measure: model.measure(entry.measureID), showDate: true)
                    .swipeActions {
                        Button { model.restore(entry.id); load() } label: { Label("Restore", systemImage: "arrow.uturn.backward") }
                            .tint(.green)
                    }
            }
        }
        .navigationTitle("Recently Deleted")
        .onAppear(perform: load)
    }

    private func load() { entries = model.store.deletedEntries() }
}
