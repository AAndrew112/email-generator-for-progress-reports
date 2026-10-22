import Foundation

/// The measures LifeLog starts with. IDs are fixed so a Watch that has never
/// talked to its iPhone still logs against the same measure IDs.
public enum Seed {
    /// Seed definitions carry an old timestamp so any user edit wins during sync.
    public static let seedDate = Date(timeIntervalSince1970: 1_767_225_600) // 2026-01-01T00:00:00Z
    public static let seedDevice = "seed"

    static func measureID(_ n: Int) -> UUID {
        UUID(uuidString: String(format: "1F0E0000-0000-4000-8000-%012d", n))!
    }

    static func fieldID(_ m: Int, _ f: Int) -> UUID {
        UUID(uuidString: String(format: "2F0E0000-0000-4000-8000-%06d%06d", m, f))!
    }

    static func presetID(_ m: Int, _ p: Int) -> UUID {
        UUID(uuidString: String(format: "3F0E0000-0000-4000-8000-%06d%06d", m, p))!
    }

    // MARK: Anchor sets (fully labelled five-point scales, 0–4)

    public static func anchors(_ labels: [String], from start: Int = 0) -> [RatingAnchor] {
        labels.enumerated().map { RatingAnchor(value: start + $0.offset, label: $0.element) }
    }

    public static let intensity = ["Not at all", "A little", "Moderately", "Quite a bit", "Extremely"]
    public static let quality = ["Very poor", "Poor", "Fair", "Good", "Very good"]
    public static let degree = ["Not at all", "Slightly", "Moderately", "Very", "Completely"]
    public static let amount = ["None", "A little", "Some", "A lot", "A great deal"]
    public static let level = ["Very low", "Low", "Moderate", "High", "Very high"]
    public static let severity = ["None", "Mild", "Moderate", "Severe", "Very severe"]

    static func rating(_ m: Int, _ f: Int, key: String = "rating", label: String, prompt: String,
                       labels: [String], required: Bool = true,
                       aggregate: DailyAggregate = .automatic) -> FieldDefinition {
        FieldDefinition(id: fieldID(m, f), key: key, label: label, prompt: prompt, type: .rating,
                        minValue: 0, maxValue: Double(labels.count - 1), step: 1,
                        anchors: anchors(labels), isRequired: required, dailyAggregate: aggregate)
    }

    static let triggerOptions = ["Bored", "Avoiding a task", "Stressed or anxious", "Tired", "Notification",
                                 "Automatic / habit", "Waiting", "Lonely or social", "Unknown"].map(ChoiceOption.init)
    static let platformOptions = ["Instagram", "TikTok", "YouTube", "Reddit", "X / Twitter", "News",
                                  "Messages", "Email", "Other"].map(ChoiceOption.init)
    static let deviceOptions = ["Phone", "Computer", "Tablet", "TV", "Watch"].map(ChoiceOption.init)

    static let minutes: (Double) -> Double = { $0 * 60 }

    public static func measures() -> [Measure] {
        var list: [Measure] = []
        func add(_ m: Measure) {
            var m = m
            m.sortOrder = list.count * 10
            m.createdAt = seedDate
            m.modifiedAt = seedDate
            m.revision = 1
            m.modifiedBy = seedDevice
            list.append(m)
        }

        // MARK: Sleep (morning)
        add(Measure(
            id: measureID(1), key: "sleep_times", name: "Sleep times",
            prompt: "Last night", group: "Sleep", icon: "bed.double.fill", color: "indigo",
            fields: [
                FieldDefinition(id: fieldID(1, 1), key: "bedtime", label: "Got into bed",
                                prompt: "When did you get into bed?", type: .time, dailyAggregate: .last),
                FieldDefinition(id: fieldID(1, 2), key: "sleep_onset", label: "Fell asleep",
                                prompt: "Roughly when did you fall asleep?", type: .time, dailyAggregate: .last),
                FieldDefinition(id: fieldID(1, 3), key: "wake_time", label: "Woke up",
                                prompt: "When did you wake up for the day?", type: .time, dailyAggregate: .last),
                FieldDefinition(id: fieldID(1, 4), key: "sleep_duration", label: "Time asleep",
                                prompt: "Calculated from fell asleep → woke up. Adjust if you were awake a long time overnight.",
                                type: .duration, quickValues: [5, 6, 7, 8, 9].map { $0 * 3600 }, dailyAggregate: .last),
            ],
            cardinality: .oncePerDay, inMorningCheckIn: true, inQuickLog: false))

        add(Measure(
            id: measureID(2), key: "sleep_quality", name: "Sleep quality", group: "Sleep",
            icon: "moon.zzz.fill", color: "indigo",
            fields: [rating(2, 1, label: "Sleep quality", prompt: "How well did you sleep?", labels: quality)],
            cardinality: .oncePerDay, inMorningCheckIn: true, inQuickLog: false))

        add(Measure(
            id: measureID(3), key: "restedness", name: "Restedness", group: "Sleep",
            icon: "sun.max.fill", color: "orange",
            fields: [rating(3, 1, label: "Restedness", prompt: "How rested do you feel right now?", labels: degree)],
            cardinality: .oncePerDay, inMorningCheckIn: true, inQuickLog: false))

        // MARK: Mind (evening)
        func evening(_ n: Int, _ key: String, _ name: String, _ icon: String, _ color: String,
                     _ prompt: String, _ labels: [String]) {
            add(Measure(id: measureID(n), key: key, name: name, group: "Mind", icon: icon, color: color,
                        fields: [rating(n, 1, label: name, prompt: prompt, labels: labels)],
                        cardinality: .oncePerDay, inEveningCheckIn: true, inQuickLog: false))
        }
        evening(4, "mood", "Mood", "face.smiling", "yellow",
                "Overall, how was your mood today?", ["Very low", "Low", "Okay", "Good", "Very good"])
        evening(5, "anxiety", "Anxiety", "waveform.path.ecg", "red",
                "Overall, how anxious did you feel today?", intensity)
        evening(6, "brain_fog", "Brain fog", "cloud.fog.fill", "gray",
                "How foggy or slowed was your thinking today?", intensity)
        evening(7, "mental_energy", "Mental energy", "bolt.fill", "orange",
                "How much mental energy did you have today?", level)
        evening(8, "focus", "Focus", "scope", "blue",
                "When you tried to concentrate today, how well could you focus?",
                ["Very poorly", "Poorly", "Fairly well", "Well", "Very well"])
        evening(9, "work_avoidance", "Work avoidance", "arrow.uturn.backward.circle.fill", "pink",
                "How much did you avoid or put off work you meant to do today?", intensity)
        evening(10, "work_progress", "Meaningful progress", "flag.checkered", "green",
                "How much meaningful progress did you make on work that matters to you?", amount)
        evening(11, "fulfillment", "Fulfillment", "sparkles", "purple",
                "How fulfilling did today feel?", degree)

        // MARK: Screen (quick log)
        add(Measure(
            id: measureID(12), key: "scroll_episode", name: "Scrolling episode",
            prompt: "Time spent scrolling you’d count as an episode", group: "Screen",
            icon: "scroll.fill", color: "teal",
            fields: [
                FieldDefinition(id: fieldID(12, 1), key: "duration", label: "Duration", prompt: "How long?",
                                type: .duration, isRequired: true,
                                quickValues: [2, 5, 10, 15, 20, 30, 45, 60, 90, 120].map(minutes),
                                dailyAggregate: .sum),
                FieldDefinition(id: fieldID(12, 2), key: "platform", label: "App / platform", type: .choice,
                                options: platformOptions),
                FieldDefinition(id: fieldID(12, 3), key: "trigger", label: "Trigger / context", type: .multiChoice,
                                options: triggerOptions),
                FieldDefinition(id: fieldID(12, 4), key: "device", label: "Device", type: .choice,
                                options: deviceOptions),
            ],
            timing: .episode, isFavorite: true))

        add(Measure(
            id: measureID(13), key: "screen_urge", name: "Screen urge",
            prompt: "An urge to check, open or scroll", group: "Screen",
            icon: "hand.tap.fill", color: "teal",
            fields: [
                FieldDefinition(id: fieldID(13, 1), key: "outcome", label: "Outcome", prompt: "What happened?",
                                type: .choice, options: [ChoiceOption(key: "resisted", label: "Resisted"),
                                                         ChoiceOption(key: "gave_in", label: "Gave in")],
                                isRequired: true),
                rating(13, 2, key: "strength", label: "Strength", prompt: "How strong was the urge?",
                       labels: ["Very weak", "Weak", "Moderate", "Strong", "Very strong"], required: false),
                FieldDefinition(id: fieldID(13, 3), key: "trigger", label: "Trigger / context", type: .multiChoice,
                                options: triggerOptions),
                FieldDefinition(id: fieldID(13, 4), key: "platform", label: "App / platform", type: .choice,
                                options: platformOptions),
            ],
            presets: [
                Preset(id: presetID(13, 1), label: "Urge resisted", values: ["outcome": .choices(["resisted"])]),
                Preset(id: presetID(13, 2), label: "Gave in", values: ["outcome": .choices(["gave_in"])]),
            ]))

        add(Measure(
            id: measureID(14), key: "phone_pickup", name: "Automatic pickup",
            prompt: "Picked up the phone without deciding to", group: "Screen",
            icon: "iphone.gen3.radiowaves.left.and.right", color: "teal",
            fields: [
                FieldDefinition(id: fieldID(14, 1), key: "trigger", label: "Trigger / context", type: .multiChoice,
                                options: triggerOptions),
                FieldDefinition(id: fieldID(14, 2), key: "device", label: "Device", type: .choice,
                                options: deviceOptions),
            ],
            isFavorite: true))

        add(Measure(
            id: measureID(15), key: "screen_time_total", name: "Screen Time total", group: "Screen",
            icon: "hourglass", color: "teal",
            fields: [
                FieldDefinition(id: fieldID(15, 1), key: "total", label: "Screen Time",
                                prompt: "What does Screen Time show for today?", type: .duration,
                                quickValues: [1, 2, 3, 4, 5, 6, 8].map { $0 * 3600 }, dailyAggregate: .last),
            ],
            cardinality: .oncePerDay, inEveningCheckIn: true, inQuickLog: false, isActive: false))

        // MARK: Intake
        add(Measure(
            id: measureID(16), key: "caffeine", name: "Caffeine", group: "Intake",
            icon: "cup.and.saucer.fill", color: "brown",
            fields: [
                FieldDefinition(id: fieldID(16, 1), key: "source", label: "Source", type: .choice,
                                options: ["Coffee", "Espresso", "Tea", "Energy drink", "Soda", "Pre-workout",
                                          "Supplement", "Other"].map(ChoiceOption.init)),
                FieldDefinition(id: fieldID(16, 2), key: "dose", label: "Amount", type: .number, unit: "mg",
                                minValue: 0, step: 5, quickValues: [30, 50, 63, 95, 150, 200], dailyAggregate: .sum),
            ],
            presets: [
                Preset(id: presetID(16, 1), label: "Coffee", values: ["source": .choices(["coffee"]), "dose": .number(95)]),
                Preset(id: presetID(16, 2), label: "Espresso", values: ["source": .choices(["espresso"]), "dose": .number(63)], isFavorite: false),
                Preset(id: presetID(16, 3), label: "Tea", values: ["source": .choices(["tea"]), "dose": .number(47)], isFavorite: false),
            ]))

        add(Measure(
            id: measureID(17), key: "medication", name: "Medication",
            prompt: "Tip: save each regular medication as a preset for one-tap logging.", group: "Intake",
            icon: "pills.fill", color: "mint",
            fields: [
                FieldDefinition(id: fieldID(17, 1), key: "name", label: "Medication", prompt: "Which medication?",
                                type: .text, isRequired: true),
                FieldDefinition(id: fieldID(17, 2), key: "dose", label: "Dose", type: .number, minValue: 0,
                                dailyAggregate: DailyAggregate.none),
                FieldDefinition(id: fieldID(17, 3), key: "unit", label: "Unit", type: .choice,
                                options: ["mg", "mcg", "g", "mL", "tablet", "capsule", "drop", "puff", "IU"].map(ChoiceOption.init),
                                defaultValue: .choices(["mg"])),
                FieldDefinition(id: fieldID(17, 4), key: "side_effects", label: "Side effects", type: .text),
            ],
            isFavorite: true))

        // MARK: Skin
        add(Measure(
            id: measureID(18), key: "seb_derm", name: "Seborrheic dermatitis", group: "Skin",
            icon: "allergens", color: "red",
            fields: [
                rating(18, 1, key: "severity", label: "Severity", prompt: "How severe is it right now?", labels: severity,
                       aggregate: .max),
                FieldDefinition(id: fieldID(18, 2), key: "locations", label: "Locations", prompt: "Where?",
                                type: .multiChoice,
                                options: ["Scalp", "Hairline", "Eyebrows", "Between eyebrows", "Eyelids",
                                          "Sides of nose", "Nasolabial folds", "Cheeks", "Beard area",
                                          "Chin", "Ears", "Behind ears", "Chest", "Upper back", "Other"].map(ChoiceOption.init)),
                FieldDefinition(id: fieldID(18, 3), key: "photo", label: "Photo", type: .photo),
            ],
            isFavorite: true))

        return list
    }
}
