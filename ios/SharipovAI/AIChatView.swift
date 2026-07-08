import SwiftUI

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String
    let text: String
}

struct AIChatView: View {
    @State private var text = ""
    @State private var messages: [ChatMessage] = [
        ChatMessage(role: "AI", text: "Привет, Самандар. Я SharipovAI. Спроси про портфель, рынок, риск или сделки.")
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                SATheme.background.ignoresSafeArea()
                VStack(spacing: 12) {
                    ScrollView {
                        VStack(spacing: 12) {
                            ForEach(messages) { message in
                                HStack {
                                    if message.role == "Вы" { Spacer() }
                                    Text(message.text)
                                        .padding(14)
                                        .background(message.role == "Вы" ? SATheme.accent : SATheme.panelSoft)
                                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                                    if message.role == "AI" { Spacer() }
                                }
                            }
                        }
                        .padding()
                    }

                    HStack {
                        TextField("Напиши AI...", text: $text)
                            .textFieldStyle(.plain)
                            .padding(12)
                            .background(SATheme.panelSoft)
                            .clipShape(Capsule())

                        Button(action: send) {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.system(size: 34))
                        }
                        .tint(SATheme.accent)
                    }
                    .padding()
                }
            }
            .navigationTitle("AI чат")
        }
    }

    private func send() {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        messages.append(ChatMessage(role: "Вы", text: value))
        text = ""
        messages.append(ChatMessage(role: "AI", text: "Понял. В следующем этапе подключу этот чат к backend SharipovAI."))
    }
}

#Preview {
    AIChatView()
        .preferredColorScheme(.dark)
}
