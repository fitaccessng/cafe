# Menu Image Review

The catalogue contains 32 distinct source entries. Thirteen entries currently have an optimized local image with source, creator, and license data in `image-manifest.json`. These are illustrative stock photos, not representations of Café Coffee Day servings.

## Local images verified

Cappuccino, Café Latte, Americano, Flat White, Hot Chocolate, Green Tea, Chai Latte, Rooibos Tea, Matcha Latte, Mixed Berry Smoothie, Green Smoothie, Blueberry Smoothie, and the duplicate R22 Chicken & Mayo Sandwich draft.

## Image required

Chicken & Mayo Sandwich (R25), Egg Mayo Sandwich, Club Sandwich, Cheese & Tomato Sandwich, Cheese & Tomato Croissants, Chicken Mayo Croissant, Plain Croissants, Mango Smoothie, Strawberry Smoothie, Peanut Butter Smoothie, Oatmeal Smoothie, Cookies & Cream Smoothie, Earl Grey Tea, Chocolate Milkshake, Banana Milkshake, Berry Milkshake, Bubblegum Milkshake, and Strawberry Milkshake.

Those products currently use clearly labeled local category placeholders. The Coddies entry uses a neutral placeholder because its identity is unconfirmed. No unsupported product photo is marked as verified.

## Catalogue review

- Chicken & Mayo Sandwich, R22: duplicate entry with a conflicting price; unpublished until business confirmation.
- Assorted Giant Coddies, R10: source wording needs verification; unpublished until business confirmation.

To retry curated source downloads, use `python scripts/fetch_menu_images.py`. The downloader validates image bytes, converts accepted photos to local optimized JPEGs, and only records successful downloads with source, creator, and license metadata. Wikimedia Commons rate limits prevented several otherwise relevant candidates from downloading during the initial run; retry them later or replace them with business-authorized photographs.