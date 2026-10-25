import Foundation

/// What a card is doing right now. A card with no entry is idle.
enum CardStatus: Equatable {
    case sending(String)
    case done(String)
    case failed(String)
}
