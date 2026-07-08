import Foundation

struct DashboardSnapshot: Codable {
    var decision: String
    var confidence: Double
    var riskLevel: String
    var equity: Double
    var pnl: Double

    static let demo = DashboardSnapshot(
        decision: "NO DECISION",
        confidence: 0,
        riskLevel: "LOW",
        equity: 10_000,
        pnl: 0
    )
}

final class APIClient: ObservableObject {
    static let shared = APIClient()

    // Замени на адрес Render, например: https://sharipovai.onrender.com
    private let baseURL = URL(string: "https://example.onrender.com")!

    func loadDashboard() async -> DashboardSnapshot {
        let url = baseURL.appending(path: "api/chat/message")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["message": "покажи портфель"])

        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            let run = json?["run"] as? [String: Any]
            return DashboardSnapshot(
                decision: run?["decision"] as? String ?? "NO DECISION",
                confidence: run?["confidence"] as? Double ?? 0,
                riskLevel: run?["risk_level"] as? String ?? "LOW",
                equity: run?["paper_equity"] as? Double ?? 10_000,
                pnl: run?["paper_pnl"] as? Double ?? 0
            )
        } catch {
            return .demo
        }
    }
}
