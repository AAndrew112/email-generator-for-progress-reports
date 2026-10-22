import SwiftUI
import UniformTypeIdentifiers
import LifeLogKit

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(WatchSync.self) private var sync
    @State private var exporting = false
    @State private var shareURL: URL?
    @State private var exportSummary: String?
    @State private var importing = false
    @State private var message: String?
    @State private var studyItem: StudyItem?

    struct StudyItem: Identifiable {
        let id = UUID()
        let study: Study
        let isNew: Bool
    }

    private func setting<T>(_ keyPath: WritableKeyPath<AppSettings, T>) -> Binding<T> {
        Binding(get: { model.settings[keyPath: keyPath] }, set: { value in
            var s = model.settings
            s[keyPath: keyPath] = value
            model.saveSettings(s)
        })
    }

    private func reminderTime(_ keyPath: WritableKeyPath<AppSettings, ReminderTime>) -> Binding<Date> {
        Binding(get: {
            let r = model.settings[keyPath: keyPath]
            return Calendar.current.date(bySettingHour: r.hour, minute: r.minute, second: 0, of: Date()) ?? Date()
        }, set: { date in
            var s = model.settings
            let c = Calendar.current.dateComponents([.hour, .minute], from: date)
            s[keyPath: keyPath].hour = c.hour ?? 8
            s[keyPath: keyPath].minute = c.minute ?? 0
            model.saveSettings(s)
            Task { await Reminders.apply(s) }
        })
    }

    private func reminderEnabled(_ keyPath: WritableKeyPath<AppSettings, ReminderTime>) -> Binding<Bool> {
        Binding(get: { model.settings[keyPath: keyPath].isEnabled }, set: { on in
            var s = model.settings
            s[keyPath: keyPath].isEnabled = on
            model.saveSettings(s)
            Task {
                let ok = await Reminders.apply(s)
                if !ok { message = "Notifications are turned off for LifeLog. Enable them in the Settings app." }
            }
        })
    }

    var body: some View {
        NavigationStack {
            Form {
                studySection
                checkInSection
                healthSection
                watchSection
                dataSection
                Section("Privacy") {
                    Label("Everything stays on your iPhone and Apple Watch. No account, no analytics, no servers. Data leaves the device only when you export it.",
                          systemImage: "lock.shield")
                        .font(.callout)
                    LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
                }
            }
            .navigationTitle("Settings")
            .sheet(item: $studyItem) { item in
                StudyEditor(study: item.study, isNew: item.isNew).environment(model)
            }
            .sheet(item: Binding(get: { shareURL.map(ShareItem.init) }, set: { if $0 == nil { shareURL = nil } })) { item in
                ActivityView(items: [item.url]).ignoresSafeArea()
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
                handleImport(result)
            }
            .alert("LifeLog", isPresented: Binding(get: { message != nil }, set: { if !$0 { message = nil } })) {
                Button("OK") { message = nil }
            } message: {
                Text(message ?? "")
            }
        }
    }

    private var studySection: some View {
        Section {
            ForEach(model.settings.studies) { s in
                Button { studyItem = StudyItem(study: s, isNew: false) } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.name).foregroundStyle(.primary)
                        Text("\(s.startDay) → \(s.endDay) · \(s.lengthDays) days\(s.dayNumber(for: model.todayKey).map { " · today is day \($0)" } ?? "")")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .onDelete { offsets in
                var s = model.settings
                s.studies.remove(atOffsets: offsets)
                model.saveSettings(s)
            }
            Button {
                studyItem = StudyItem(study: Study(name: "", startDay: model.todayKey, lengthDays: 28), isNew: true)
            } label: {
                Label("Add Study Period", systemImage: "plus.circle.fill")
            }
        } header: {
            Text("Study periods")
        } footer: {
            Text("Exports get study and study_day columns for days inside a study period.")
        }
    }

    private var checkInSection: some View {
        Section {
            Picker("Day starts at", selection: setting(\.dayBoundaryHour)) {
                ForEach(0...6, id: \.self) { h in Text(hourLabel(h)).tag(h) }
            }
            Picker("Evening check-in from", selection: setting(\.eveningStartsHour)) {
                ForEach(12...22, id: \.self) { h in Text(hourLabel(h)).tag(h) }
            }
            Toggle("Morning reminder", isOn: reminderEnabled(\.morningReminder))
            if model.settings.morningReminder.isEnabled {
                DatePicker("Time", selection: reminderTime(\.morningReminder), displayedComponents: .hourAndMinute)
            }
            Toggle("Evening reminder", isOn: reminderEnabled(\.eveningReminder))
            if model.settings.eveningReminder.isEnabled {
                DatePicker("Time", selection: reminderTime(\.eveningReminder), displayedComponents: .hourAndMinute)
            }
        } header: {
            Text("Days & check-ins")
        } footer: {
            Text("Anything logged before \(hourLabel(model.settings.dayBoundaryHour)) counts toward the previous day, so a 1 AM scroll belongs to the night before.")
        }
    }

    private var healthSection: some View {
        Section {
            Toggle("Pre-fill sleep from Apple Health", isOn: Binding(get: { model.settings.healthKitSleepPrefill }, set: { on in
                var s = model.settings
                s.healthKitSleepPrefill = on
                model.saveSettings(s)
                if on { Task { _ = await HealthSleep.shared.requestAuthorization() } }
            }))
            .disabled(!HealthSleep.shared.isAvailable)
        } header: {
            Text("Apple Health")
        } footer: {
            Text("Optional. LifeLog only reads sleep, only to suggest times in the morning check-in, which you confirm or edit. Nothing is written to Health.")
        }
    }

    private var watchSection: some View {
        Section {
            LabeledContent("Apple Watch", value: !sync.isPaired ? "Not paired" : (sync.isCounterpartInstalled ? "LifeLog installed" : "App not installed"))
            if let r = sync.lastReceivedAt {
                LabeledContent("Last received", value: r.formatted(.relative(presentation: .named)))
            }
            if let s = sync.lastSentAt {
                LabeledContent("Last sent", value: s.formatted(.relative(presentation: .named)))
            }
            if let e = sync.lastError { Text(e).font(.caption).foregroundStyle(.orange) }
            Button("Sync Now") { sync.pushPending() }
            Button("Resend Everything") { sync.resyncEverything() }
        } header: {
            Text("Sync")
        } footer: {
            Text("Phone and Watch exchange changes directly over WatchConnectivity. Logs made on the Watch while the phone is away are delivered automatically later.")
        }
    }

    private var dataSection: some View {
        Section {
            Button {
                export()
            } label: {
                HStack {
                    Label("Export CSV + JSON", systemImage: "square.and.arrow.up")
                    if exporting { Spacer(); ProgressView() }
                }
            }
            .disabled(exporting)
            if let exportSummary { Text(exportSummary).font(.caption).foregroundStyle(.secondary) }
            Button { importing = true } label: { Label("Import LifeLog Backup (.json)", systemImage: "square.and.arrow.down") }
            LabeledContent("Entries", value: "\(model.store.entryCount())")
        } header: {
            Text("Data")
        } footer: {
            Text("Exports a .zip with tidy (observations.csv) and per-day (daily.csv) tables, a data dictionary, check-ins, the full edit history, lifelog.json and photos. Importing lifelog.json merges it without creating duplicates.")
        }
    }

    private func hourLabel(_ h: Int) -> String {
        let date = Calendar.current.date(bySettingHour: h, minute: 0, second: 0, of: Date()) ?? Date()
        return date.formatted(date: .omitted, time: .shortened)
    }

    private func export() {
        exporting = true
        let store = model.store
        Task.detached(priority: .userInitiated) {
            do {
                let (url, result) = try ExportService.makeExport(store: store)
                await MainActor.run {
                    exporting = false
                    exportSummary = "\(result.entryCount) entries · \(result.dayCount) days · \(result.photoCount) photos"
                        + (result.missingPhotos > 0 ? " · \(result.missingPhotos) photos missing" : "")
                    shareURL = url
                }
            } catch {
                await MainActor.run {
                    exporting = false
                    message = "Export failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func handleImport(_ result: Result<URL, Error>) {
        switch result {
        case .failure(let error):
            message = error.localizedDescription
        case .success(let url):
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let data = try Data(contentsOf: url)
                let r = try BackupImporter.importJSON(data, into: model.store)
                model.reload()
                WatchSync.shared.schedulePush()
                message = "Imported: \(r.inserted) new, \(r.updated) updated, \(r.ignored) already up to date."
            } catch {
                message = "\(error)"
            }
        }
    }
}

struct ShareItem: Identifiable {
    let url: URL
    var id: String { url.path }
}

struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct StudyEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var study: Study
    @State private var start: Date
    let isNew: Bool

    init(study: Study, isNew: Bool) {
        _study = State(initialValue: study)
        let p = DayKey.parse(study.startDay)
        _start = State(initialValue: p.flatMap { Calendar.current.date(from: DateComponents(year: $0.year, month: $0.month, day: $0.day)) } ?? Date())
        self.isNew = isNew
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name", text: $study.name)
                DatePicker("First day", selection: $start, displayedComponents: .date)
                Stepper("Length: \(study.lengthDays) days", value: $study.lengthDays, in: 1...3650)
                LabeledContent("Last day", value: endDay)
            }
            .navigationTitle(isNew ? "New Study Period" : "Study Period")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }.disabled(study.name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }

    private var startKey: String { DayKey.calendarDay(for: start, timeZone: .current) }

    private var endDay: String {
        var s = study
        s.startDay = startKey
        return s.endDay
    }

    private func save() {
        var s = model.settings
        var updated = study
        updated.startDay = startKey
        if let i = s.studies.firstIndex(where: { $0.id == updated.id }) { s.studies[i] = updated } else { s.studies.append(updated) }
        model.saveSettings(s)
        dismiss()
    }
}
