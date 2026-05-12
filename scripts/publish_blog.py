import sqlite3
import datetime
import os
import re

def slugify(text):
    # Basit slugify (URL dostu metin)
    text = text.lower()
    # Türkçe karakter dönüşümü
    tr_map = str.maketrans("çğıöşü", "cgiosu")
    text = text.translate(tr_map)
    text = re.sub(r'[^a-z0-9\-]', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')

def publish_all():
    blog_dir = 'blog'
    db_path = 'storage/vidinsight_saas.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    for filename in os.listdir(blog_dir):
        if filename.endswith('.md'):
            path = os.path.join(blog_dir, filename)
            with open(path, 'r', encoding='utf-8') as f:
                raw_content = f.read()

            title = filename.replace('.md', '').title()
            slug = filename.replace('.md', '')
            content = raw_content

            # Frontmatter ayıklama
            if raw_content.startswith('---'):
                parts = raw_content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    content = parts[2].strip()
                    
                    # Başlığı frontmatter'dan çek
                    title_match = re.search(r'title:\s*"(.*?)"', frontmatter)
                    if title_match:
                        title = title_match.group(1)

            # Veritabanı işlemi
            c.execute("SELECT id FROM blog_posts WHERE slug=?", (slug,))
            existing = c.fetchone()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if existing:
                c.execute("UPDATE blog_posts SET title=?, content=?, is_published=1 WHERE slug=?", (title, content, slug))
                print(f"Güncellendi: {title}")
            else:
                c.execute("INSERT INTO blog_posts (title, slug, content, created_at, is_published) VALUES (?, ?, ?, ?, ?)",
                          (title, slug, content, now, 1))
                print(f"Eklendi: {title}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    publish_all()
