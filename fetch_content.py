import urllib.request
import trafilatura

url = "https://www.gursahib-singh.me/"

# Fetch raw HTML
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as response:
    raw_html = response.read().decode("utf-8")

print(f"RAW HTML SIZE: {len(raw_html)} characters\n{'='*60}")

# Extract clean text using trafilatura
clean_text = trafilatura.extract(
    raw_html,
    include_comments=False,
    include_tables=True,
    no_fallback=False
)

print(f"CLEAN TEXT SIZE: {len(clean_text) if clean_text else 0} characters\n{'='*60}")
print("EXTRACTED CONTENT:")
print(clean_text)

# Save output to file
with open("extracted_content.txt", "w", encoding="utf-8") as f:
    f.write(f"RAW HTML SIZE: {len(raw_html)} characters\n")
    f.write(f"{'='*60}\n\n")
    f.write(f"CLEAN TEXT SIZE: {len(clean_text) if clean_text else 0} characters\n")
    f.write(f"{'='*60}\n\n")
    f.write("EXTRACTED CONTENT:\n")
    f.write(clean_text if clean_text else "No content extracted")

print("\n\nOutput saved to extracted_content.txt")
