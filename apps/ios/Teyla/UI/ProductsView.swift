import SwiftUI

/// Where each product stands: waiting questions, open issues, PRs that wait on you, the next step.
struct ProductsView: View {
    @Environment(AppModel.self) private var model
    @Binding var showNewTask: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let snapshot = model.snapshot {
                        if snapshot.products.isEmpty {
                            Text("No products yet.").foregroundStyle(.secondary)
                        }
                        ForEach(snapshot.products) { product in
                            ProductCard(product: product)
                        }
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
            }
            .background(Color(.systemGroupedBackground))
            .refreshable { await model.refresh() }
            .navigationTitle("Products")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: { Text("New task").fontWeight(.semibold) }
                        .disabled(model.snapshot == nil)
                }
            }
        }
    }
}

private struct ProductCard: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(Format.product(product.name)).font(.headline)
                Spacer(minLength: 8)
                Pill(text: stateLabel, color: stateColor)
            }
            if !product.line.isEmpty {
                Text(product.line)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 16) {
                Stat(value: product.waiting, label: "waiting", highlight: product.waiting > 0)
                Stat(value: product.issues, label: product.issues == 1 ? "issue" : "issues", highlight: false)
                Stat(value: product.prsWaiting, label: product.prsWaiting == 1 ? "PR waiting" : "PRs waiting",
                     highlight: product.prsWaiting > 0)
            }
            .padding(.top, 2)
            if !product.next.isEmpty {
                Divider()
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("Next").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text(product.next).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .card()
        .accessibilityElement(children: .combine)
    }

    private var stateLabel: String {
        switch product.state {
        case .waiting: return "needs you"
        case .shipped: return "shipped"
        case .quiet: return "quiet"
        case .active: return "active"
        }
    }

    private var stateColor: Color {
        switch product.state {
        case .waiting: return .orange
        case .shipped: return .green
        case .quiet: return .secondary
        case .active: return .blue
        }
    }
}

private struct Stat: View {
    let value: Int
    let label: String
    let highlight: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text("\(value)")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(highlight ? Color.orange : Color.primary)
                .monospacedDigit()
            Text(label).font(.footnote).foregroundStyle(.secondary)
        }
    }
}
