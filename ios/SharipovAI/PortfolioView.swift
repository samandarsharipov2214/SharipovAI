import SwiftUI

struct PortfolioView: View {
    var body: some View {
        NavigationStack {
            ZStack {
                SATheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Демо-портфель")
                            .font(.largeTitle.bold())
                        AssetRow(symbol: "BTC", name: "Bitcoin", value: "6721.42 USDT", change: "+52.40")
                        AssetRow(symbol: "SOL", name: "Solana", value: "856.75 USDT", change: "+31.20")
                        AssetRow(symbol: "USDT", name: "Cash", value: "3421.83 USDT", change: "0.00")
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Портфель")
        }
    }
}

struct AssetRow: View {
    let symbol: String
    let name: String
    let value: String
    let change: String

    var body: some View {
        HStack {
            ZStack {
                Circle().fill(SATheme.accent.opacity(0.22))
                Text(String(symbol.prefix(1))).bold()
            }
            .frame(width: 44, height: 44)
            VStack(alignment: .leading) {
                Text(symbol).bold()
                Text(name).font(.caption).foregroundStyle(SATheme.textMuted)
            }
            Spacer()
            VStack(alignment: .trailing) {
                Text(value).bold()
                Text(change).font(.caption).foregroundStyle(change.hasPrefix("-") ? SATheme.negative : SATheme.positive)
            }
        }
        .saPanel()
    }
}

#Preview {
    PortfolioView()
        .preferredColorScheme(.dark)
}
