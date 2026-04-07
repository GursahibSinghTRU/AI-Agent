import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove all non-ASCII characters
content = re.sub(r'[^\x00-\x7F]+', '', content)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ Cleaned up all non-ASCII characters from index.html')
