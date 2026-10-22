import SwiftUI
import LifeLogKit

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router

    var body: some View {
        @Bindable var router = router
        TabView(selection: $router.tab) {
            TodayView()
                .tabItem { Label("Today", systemImage: "sun.max") }
                .tag(Router.AppTab.today)
            HistoryView()
                .tabItem { Label("History", systemImage: "clock.arrow.circlepath") }
                .tag(Router.AppTab.history)
            MeasuresView()
                .tabItem { Label("Measures", systemImage: "slider.horizontal.3") }
                .tag(Router.AppTab.measures)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(Router.AppTab.settings)
        }
        .overlay(alignment: .bottom) { ToastView().padding(.bottom, 58) }
        .sheet(item: $router.sheet) { sheet in
            sheetContent(sheet).environment(model).environment(router)
        }
        .alert("Something went wrong", isPresented: Binding(get: { model.errorMessage != nil },
                                                            set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK") { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    @ViewBuilder
    private func sheetContent(_ sheet: Router.Sheet) -> some View {
        switch sheet {
        case .checkIn(let kind):
            CheckInView(kind: kind)
        case .newEntry(let actionID):
            if let action = QuickAction.find(actionID, in: model.measures) {
                if action.measure.cardinality == .oncePerDay, let existing = model.todayEntry(for: action.measure) {
                    EntryFormView(mode: .edit(existing))
                } else {
                    EntryFormView(mode: .new(action, context: .quickLog, at: nil), quick: true)
                        .presentationDetents([.medium, .large])
                }
            } else {
                ContentUnavailableView("Not found", systemImage: "questionmark.circle",
                                       description: Text("This item no longer exists."))
            }
        case .editEntry(let id):
            if let entry = model.store.entry(id: id) {
                EntryFormView(mode: .edit(entry))
            } else {
                ContentUnavailableView("Entry not found", systemImage: "questionmark.circle")
            }
        case .pickMeasure:
            MeasurePickerView()
        }
    }
}

/// "Logged · Undo · Edit" banner after one-tap logging.
struct ToastView: View {
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router

    var body: some View {
        if let toast = model.toast {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).font(.title3)
                VStack(alignment: .leading, spacing: 1) {
                    Text(toast.title).font(.subheadline.weight(.semibold))
                    if !toast.detail.isEmpty {
                        Text(toast.detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 8)
                Button("Edit") {
                    model.toast = nil
                    router.sheet = .editEntry(toast.entryID)
                }
                .font(.subheadline.weight(.semibold))
                Button("Undo") { model.undo(toast) }
                    .font(.subheadline.weight(.semibold))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
            .padding(.horizontal)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .id(toast.id)
        }
    }
}

/// Every quick-loggable measure and preset, searchable.
struct MeasurePickerView: View {
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var search = ""
    @State private var backdate = false
    @State private var when = Date()
    @State private var formAction: QuickAction?

    private var actions: [QuickAction] {
        let all = QuickLogger.allActions(from: model.measures)
            + model.activeMeasures.filter { !$0.inQuickLog }.map { QuickAction(measure: $0, preset: nil) }
        guard !search.isEmpty else { return all }
        return all.filter { $0.title.localizedCaseInsensitiveContains(search) || $0.measure.group.localizedCaseInsensitiveContains(search) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Toggle("Log at an earlier time", isOn: $backdate.animation())
                    if backdate {
                        DatePicker("Time", selection: $when, in: ...Date())
                    }
                }
                let grouped = Dictionary(grouping: actions, by: { $0.measure.group })
                ForEach(model.groups.filter { grouped[$0] != nil }, id: \.self) { group in
                    Section(group) {
                        ForEach(grouped[group] ?? []) { action in
                            Button { pick(action) } label: {
                                HStack(spacing: 12) {
                                    MeasureIcon(symbol: action.measure.icon, color: action.measure.color, size: 30)
                                    VStack(alignment: .leading) {
                                        Text(action.title).foregroundStyle(.primary)
                                        if let s = action.subtitle { Text(s).font(.caption).foregroundStyle(.secondary) }
                                    }
                                    Spacer()
                                    if action.isComplete && action.measure.cardinality == .multiple && !backdate {
                                        Image(systemName: "bolt.fill").font(.caption).foregroundStyle(.secondary)
                                            .accessibilityLabel("One tap")
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .always))
            .navigationTitle("Log")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(item: $formAction) { action in
                EntryFormView(mode: .new(action, context: backdate ? .manual : .quickLog, at: backdate ? when : nil),
                              quick: !backdate)
                    .environment(model)
                    .presentationDetents(backdate ? [.large] : [.medium, .large])
                    .onDisappear { if model.toast != nil { dismiss() } }
            }
        }
    }

    private func pick(_ action: QuickAction) {
        if backdate {
            formAction = action
            return
        }
        switch model.quickLog(action) {
        case .logged:
            dismiss()
        case .needsInput(_, let existing):
            if let existing {
                dismiss()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { router.sheet = .editEntry(existing.id) }
            } else {
                formAction = action
            }
        }
    }
}
