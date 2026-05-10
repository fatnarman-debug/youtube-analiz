import os
import re

def add_seo_to_template(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    filename = os.path.basename(filepath)
    url_path = filename.replace('.html', '')
    if url_path == 'index':
        url_path = ''

    canonical_url = f"https://vidinsight.com/{url_path}"
    
    modified = False

    # 1. Check Meta Description
    if '<meta name="description"' not in content:
        desc = "VidInsight admin panel ve analiz araçları."
        if "login" in filename: desc = "VidInsight giriş sayfası."
        elif "signup" in filename: desc = "VidInsight kayıt sayfası."
        elif "admin" in filename: desc = "VidInsight admin kontrol paneli."
        elif "blog" in filename: desc = "VidInsight blog yazıları."
        elif "dashboard" in filename: desc = "VidInsight kullanıcı paneli."
        elif "free_tool" in filename: desc = "VidInsight ücretsiz youtube yorum analiz aracı."
        
        meta_tag = f'    <meta name="description" content="{desc}">\n'
        content = re.sub(r'(<head[^>]*>)', r'\1\n' + meta_tag, content, count=1, flags=re.IGNORECASE)
        modified = True

    # 2. Check Canonical
    if '<link rel="canonical"' not in content:
        canonical_tag = f'    <link rel="canonical" href="{canonical_url}">\n'
        content = re.sub(r'(</head>)', canonical_tag + r'\1', content, count=1, flags=re.IGNORECASE)
        modified = True

    # 3. Check JSON-LD
    if 'application/ld+json' not in content:
        schema_type = "WebPage"
        if "blog" in filename: schema_type = "BlogPosting"
        elif "free_tool" in filename: schema_type = "WebApplication"
        elif "index" in filename: schema_type = "SoftwareApplication"
        
        schema_tag = f'''    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "{schema_type}",
      "name": "VidInsight Page",
      "url": "{canonical_url}"
    }}
    </script>
'''
        content = re.sub(r'(</head>)', schema_tag + r'\1', content, count=1, flags=re.IGNORECASE)
        modified = True

    # 4. Check H1
    if '<h1' not in content and '<H1' not in content:
        h1_title = "VidInsight " + filename.replace('.html', '').replace('_', ' ').title()
        # insert after <body> or <div class="container">
        if '<div class="container">' in content:
            h1_tag = f'\n    <h1 style="display:none;">{h1_title}</h1>\n'
            content = re.sub(r'(<div class="container"[^>]*>)', r'\1' + h1_tag, content, count=1)
            modified = True
        elif '<body' in content:
            h1_tag = f'\n    <h1 style="display:none;">{h1_title}</h1>\n'
            content = re.sub(r'(<body[^>]*>)', r'\1' + h1_tag, content, count=1, flags=re.IGNORECASE)
            modified = True

    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {filename}")

if __name__ == "__main__":
    templates_dir = "templates"
    for filename in os.listdir(templates_dir):
        if filename.endswith(".html"):
            add_seo_to_template(os.path.join(templates_dir, filename))
