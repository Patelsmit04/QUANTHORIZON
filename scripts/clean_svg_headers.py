import glob
import os
import xml.etree.ElementTree as ET

LOGOS_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'logos')
files = glob.glob(os.path.join(LOGOS_DIR, '*.svg'))

print(f"Processing {len(files)} SVG files...")
cleaned_count = 0

for f in files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        content = fp.read()

    # Remove any leading comments like <!-- by TradingView -->
    original = content
    content = content.strip()
    while content.startswith('<!--'):
        end_comment = content.find('-->')
        if end_comment != -1:
            content = content[end_comment + 3:].strip()
        else:
            break

    # Strip existing xml declaration if present
    if content.startswith('<?xml'):
        end_decl = content.find('?>')
        if end_decl != -1:
            content = content[end_decl + 2:].strip()

    # Ensure clean xml declaration at the very top
    clean_content = f'<?xml version="1.0" encoding="utf-8"?>\n{content}\n'

    if clean_content != original:
        # Validate XML before saving
        try:
            ET.fromstring(content)
            with open(f, 'w', encoding='utf-8') as fp:
                fp.write(clean_content)
            cleaned_count += 1
        except Exception as e:
            print(f"Warning: Failed to parse XML for {os.path.basename(f)}: {e}")

print(f"Successfully cleaned and standardized {cleaned_count} SVGs.")

# Run validation across all files
errors = 0
for f in files:
    try:
        ET.parse(f)
    except Exception as e:
        print(f"Validation error in {os.path.basename(f)}: {e}")
        errors += 1

print(f"Final Validation: {len(files)} total files, {errors} errors.")
