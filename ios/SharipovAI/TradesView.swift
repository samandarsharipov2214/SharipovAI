import SwiftUI

struct TradesView: View {
    private let trades = [
        ("BTC/USDT", "BUY", "+52.40 USDT", "AI купил BTC: низкий риск, сильный консенсус."),
        ("ETH/USDT", "SELL", "-18.30 USDT", "AI закрыл ETH: ухудшился импульс."),
        ("SOL/USDT", "BUY", "+31.20 USDT", "AI открыл SOL: хорошее соотношение риск/прибыль.")
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                SATheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Журнал сделок")
                            .font(.largeTitle.bold())
                        ForEach(trades, id: \.0) { trade in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(trade.0).font(.headline)
                                    Spacer()
                                    Text(trade.1)
                                        .font(.caption.bold())
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 6)
                                        .background(SATheme.accent.opacity(0.22))
                                        .clipShape(Capsule())
                                }
                                Text(trade.2)
                                    .foregroundStyle(trade.2.hasPrefix("-") ? SATheme.negative : SATheme.positive)
                                Text(trade.3)
                                    .font(.caption)
                                    .foregroundStyle(SATheme.textMuted)
                            }
                            .saPanel()
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Сделки")
        }
    }
}

#Preview {
    TradesView()
        .preferredColorScheme(.dark)
}
