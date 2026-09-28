import glob
import re

def normalize():
    files = glob.glob('static/logos/*.svg')
    modified = 0
    for f in files:
        with open(f, 'r', encoding='utf-8') as fp:
            content = fp.read()
        
        if 'viewBox' not in content and 'viewbox' not in content:
            w_match = re.search(r'width=[\"\']([0-9\.]+)[\"\']', content)
            h_match = re.search(r'height=[\"\']([0-9\.]+)[\"\']', content)
            if w_match and h_match:
                w = w_match.group(1)
                h = h_match.group(1)
                new_content = re.sub(r'<svg\b', f'<svg viewBox="0 0 {w} {h}"', content, count=1)
                with open(f, 'w', encoding='utf-8') as fp:
                    fp.write(new_content)
                modified += 1
            else:
                new_content = re.sub(r'<svg\b', '<svg viewBox="0 0 18 18"', content, count=1)
                with open(f, 'w', encoding='utf-8') as fp:
                    fp.write(new_content)
                modified += 1

    print(f"Normalized {modified} SVGs with viewBox attribute!")

if __name__ == '__main__':
    normalize()
