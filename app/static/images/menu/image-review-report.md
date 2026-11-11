# Menu Image Review

The catalogue contains 32 distinct source entries. Sixteen entries currently have an optimized local image with source, creator, and license data in `image-manifest.json`. These are illustrative stock photos, not representations of Café Coffee Day servings.

## Local images verified

Cappuccino, Café Latte, Americano, Flat White, Hot Chocolate, Green Tea, Earl Grey Tea, Chai Latte, Rooibos Tea, Matcha Latte, Mixed Berry Smoothie, Mango Smoothie, Green Smoothie, Blueberry Smoothie, Strawberry Milkshake, and the duplicate R22 Chicken & Mayo Sandwich draft.

## Image required

Chicken & Mayo Sandwich (R25), Egg Mayo Sandwich, Club Sandwich, Cheese & Tomato Sandwich, Cheese & Tomato Croissants, Chicken Mayo Croissant, Plain Croissants, Strawberry Smoothie, Peanut Butter Smoothie, Oatmeal Smoothie, Cookies & Cream Smoothie, Chocolate Milkshake, Banana Milkshake, Berry Milkshake, and Bubblegum Milkshake.

Those products currently use clearly labeled local category placeholders. The Coddies entry uses a neutral placeholder because its identity is unconfirmed. No unsupported product photo is marked as verified.

## Catalogue review

- Chicken & Mayo Sandwich, R22: duplicate entry with a conflicting price; unpublished until business confirmation.
- Assorted Giant Coddies, R10: source wording needs verification; unpublished until business confirmation.

To retry curated source downloads, use `python scripts/fetch_menu_images.py`. The downloader validates image bytes, converts accepted photos to local optimized JPEGs, and only records successful downloads with source, creator, and license metadata. Wikimedia Commons returned HTTP 429 responses for several remaining candidates; retry after the rate limit clears or replace them with business-authorized photographs.