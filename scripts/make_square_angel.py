import re

def main():
    path = 'static/logos/ANGELONE.svg'
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract all paths that are part of the emblem (first 11 path tags)
    all_paths = re.findall(r'<path[^>]+>', content)
    emblem_paths = all_paths[:11]
    
    svg = (
        '<svg viewBox="0 0 58 55" width="28" height="28" xmlns="http://www.w3.org/2000/svg">\n'
        '  <rect width="58" height="55" rx="10" fill="#0d131f"/>\n'
        '  <g transform="translate(0.5, 0.5)">\n'
        '    ' + '\n    '.join(emblem_paths) + '\n'
        '  </g>\n'
        '</svg>'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print("Created high-precision square ANGELONE emblem!")

if __name__ == '__main__':
    main()
