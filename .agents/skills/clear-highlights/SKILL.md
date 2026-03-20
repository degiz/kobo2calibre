---
name: clear-highlights
description: Remove all highlights for a book from Kobo and/or Calibre databases
compatibility: opencode
metadata:
  destructive: true
---

# Clear Highlights

## Config

Read `paths.kobo_db` and `paths.calibre_db` from `.agents/config.yaml`. If the file is missing, ask the user for paths and create it.

## Steps

1. Ask user: which DB(s) (Kobo / Calibre / both) and book name
2. Find book — confirm with user before proceeding:
   - Kobo: `SELECT VolumeID, COUNT(*) FROM Bookmark WHERE VolumeID LIKE '%<name>%' AND Text != '' GROUP BY VolumeID`
   - Calibre: `SELECT b.id, b.title, COUNT(a.id) FROM books b JOIN annotations a ON a.book = b.id WHERE b.title LIKE '%<name>%' AND a.user_type = 'local' GROUP BY b.id`
3. Show count, confirm deletion with user
4. Delete:
   - Kobo: `DELETE FROM Bookmark WHERE VolumeID = ? AND Text != ''`
   - Calibre: `DELETE FROM annotations WHERE book = ? AND user_type = 'local'`
5. Report rows deleted
