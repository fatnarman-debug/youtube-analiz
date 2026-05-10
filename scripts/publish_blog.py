import sqlite3
import datetime
import os
import re

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\-]', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')

md_path = 'blog/youtube-yorumlardan-icerik-fikri.md'
with open(md_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Extract title and remove frontmatter
title = "YouTube Yorumlarından İçerik Fikri Nasıl Çıkarılır?"
if content.startswith('---'):
    parts = content.split('---', 2)
    if len(parts) >= 3:
        content = parts[2].strip()

# Create slug
slug = "youtube-yorumlardan-icerik-fikri"

conn = sqlite3.connect('storage/vidinsight_saas.db')
c = conn.cursor()

# Check if it already exists
c.execute("SELECT id FROM blog_posts WHERE slug=?", (slug,))
existing = c.fetchone()

now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")

if existing:
    c.execute("UPDATE blog_posts SET title=?, content=?, is_published=1 WHERE slug=?", (title, content, slug))
    print("Post updated.")
else:
    c.execute("INSERT INTO blog_posts (title, slug, content, created_at, is_published) VALUES (?, ?, ?, ?, ?)",
              (title, slug, content, now, 1))
    print("Post inserted.")

conn.commit()
conn.close()
