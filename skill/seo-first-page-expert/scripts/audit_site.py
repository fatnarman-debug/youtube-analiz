import os
import re
from bs4 import BeautifulSoup

def audit_html_file(file_path):
    issues = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        soup = BeautifulSoup(content, 'html.parser')
        
        # 1. Check Title
        title = soup.find('title')
        if not title:
            issues.append("Missing <title> tag")
        elif len(title.text) > 60:
            issues.append(f"Title too long ({len(title.text)} chars)")
            
        # 2. Check Meta Description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if not meta_desc:
            issues.append("Missing meta description")
        elif len(meta_desc.get('content', '')) > 160:
            issues.append(f"Meta description too long ({len(meta_desc.get('content', ''))} chars)")
            
        # 3. Check H1
        h1s = soup.find_all('h1')
        if len(h1s) == 0:
            issues.append("Missing H1 heading")
        elif len(h1s) > 1:
            issues.append(f"Multiple H1 headings found ({len(h1s)})")
            
        # 4. Check Images Alt Tags
        images = soup.find_all('img')
        for img in images:
            if not img.get('alt'):
                issues.append(f"Image missing alt tag: {img.get('src')}")
                
        # 5. Check Canonical
        canonical = soup.find('link', rel='canonical')
        if not canonical:
            issues.append("Missing canonical link")
            
        # 6. Check Schema.org
        schema = soup.find('script', type='application/ld+json')
        if not schema:
            issues.append("Missing structured data (JSON-LD)")

    return issues

def main():
    root_dir = "."
    report = {}
    
    for root, dirs, files in os.walk(root_dir):
        if "node_modules" in root or ".git" in root or "skill" in root:
            continue
            
        for file in files:
            if file.endswith(".html"):
                file_path = os.path.join(root, file)
                issues = audit_html_file(file_path)
                if issues:
                    report[file_path] = issues
                    
    if report:
        print("--- SEO Audit Report ---")
        for file, issues in report.items():
            print(f"\nFile: {file}")
            for issue in issues:
                print(f"  - {issue}")
    else:
        print("No major SEO issues found in HTML files!")

if __name__ == "__main__":
    main()
