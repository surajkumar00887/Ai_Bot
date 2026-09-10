# MongoDB Migration Guide for main.py

## Key Changes Required

### 1. IMPORTS (Top of file)
**Remove:**
```python
import sqlite3
```

**Add:**
```python
from mongodb_config import (
    init_mongodb, close_mongodb, mongo_db,
    create_quiz, get_quiz, get_user_quizzes, update_quiz, delete_quiz,
    create_question, get_quiz_questions, get_question, update_question, delete_question,
    add_broadcast_user, add_broadcast_group, get_broadcast_users, get_broadcast_groups,
    create_autorun, get_active_autoruns, update_autorun, deactivate_autorun, get_autorun_by_quiz,
    count_questions_in_quiz, count_user_quizzes
)
```

### 2. DATABASE INITIALIZATION (main() function)

**Replace:**
```python
async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN not found in environment variables!")
        return
    
    try:
        init_db()
        migrate_fix_correct_answer()
```

**With:**
```python
async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN not found in environment variables!")
        return
    
    try:
        await init_mongodb()  # ✅ Async MongoDB init
        # No need for migrate_fix_correct_answer() - MongoDB stores correct as INTEGER by default
```

### 3. REMOVE THESE FUNCTIONS (Not needed with MongoDB)
- `init_db()` - Replaced by `init_mongodb()`
- `migrate_fix_correct_answer()` - Not needed
- All SQLite connection code

---

## Function-by-Function Changes

### `start()` function
**Old (SQLite):**
```python
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    chat_type = update.message.chat.type

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    is_private = str(chat_type) == "private"
    
    if is_private:
        cursor.execute("INSERT OR IGNORE INTO broadcast_users (chat_id) VALUES (?)", (chat_id,))
    else:
        cursor.execute("INSERT OR IGNORE INTO broadcast_groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    chat_type = update.message.chat.type

    is_private = str(chat_type) == "private"
    
    if is_private:
        await add_broadcast_user(chat_id)
    else:
        await add_broadcast_group(chat_id)
```

---

### `new_quiz_start()` → `create_quiz_handler()`
**No major changes needed, but ensure:**
- `context.user_data["quiz_build"]` stays same (in-memory)
- Database save happens in `handle_negative_selection()`

---

### `handle_negative_selection()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def handle_negative_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        
        neg_val = float(query.data.replace("neg_", "").strip())
        quiz = context.user_data.get("quiz_build", {})
        user_id = context.user_data.get("quiz_build_creator_id")
        
        if not quiz or not quiz.get("title"):
            await query.message.reply_text("❌ Error: Quiz data missing...")
            return ConversationHandler.END

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO quizzes (creator_id, title, description, timer, negative_value) VALUES (?, ?, ?, ?, ?)", 
            (user_id, quiz["title"], quiz["description"], quiz["timer"], neg_val)
        )
        qid = cursor.lastrowid
        
        for q in quiz["questions"]:
            cursor.execute(
                "INSERT INTO questions (quiz_id, question_text, options, correct_answer, explanation, pre_message) VALUES (?, ?, ?, ?, ?, ?)", 
                (qid, q["text"], json.dumps(q["options"]), q["correct"], q["explanation"], q["pre_message"])
            )
        conn.commit()
        conn.close()
```

**New (MongoDB):**
```python
async def handle_negative_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        
        neg_val = float(query.data.replace("neg_", "").strip())
        quiz = context.user_data.get("quiz_build", {})
        user_id = context.user_data.get("quiz_build_creator_id")
        
        if not quiz or not quiz.get("title"):
            await query.message.reply_text("❌ Error: Quiz data missing...")
            return ConversationHandler.END

        # ✅ Create quiz in MongoDB
        qid = await create_quiz(
            creator_id=user_id,
            title=quiz["title"],
            description=quiz["description"],
            timer=quiz["timer"],
            negative_value=neg_val
        )
        
        if not qid:
            await query.message.reply_text("❌ Error creating quiz in database")
            return ConversationHandler.END
        
        # ✅ Create all questions in MongoDB
        for q in quiz["questions"]:
            await create_question(
                quiz_id=qid,
                question_text=q["text"],
                options=q["options"],
                correct_answer=q["correct"],  # INTEGER INDEX
                explanation=q["explanation"],
                pre_message=q["pre_message"]
            )
```

---

### `view_my_quizzes()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def view_my_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.quiz_id, q.title, q.timer, COUNT(qu.id) as question_count
        FROM quizzes q
        LEFT JOIN questions qu ON q.quiz_id = qu.quiz_id
        WHERE q.creator_id = ?
        GROUP BY q.quiz_id
        ORDER BY q.quiz_id DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
```

**New (MongoDB):**
```python
async def view_my_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # ✅ Get quizzes from MongoDB
    quizzes = await get_user_quizzes(user_id)
    
    rows = []
    for quiz in quizzes:
        # ✅ Count questions
        q_count = await count_questions_in_quiz(quiz["quiz_id"])
        rows.append((quiz["quiz_id"], quiz["title"], quiz["timer"], q_count))
```

---

### `quizzes_command()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.quiz_id, q.title, q.timer, COUNT(qu.id) as question_count
        FROM quizzes q
        LEFT JOIN questions qu ON q.quiz_id = qu.quiz_id
        WHERE q.creator_id = ?
        GROUP BY q.quiz_id
        ORDER BY q.quiz_id DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
```

**New (MongoDB):**
```python
async def quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # ✅ Get quizzes from MongoDB
    quizzes = await get_user_quizzes(user_id)
    
    rows = []
    for quiz in quizzes:
        # ✅ Count questions
        q_count = await count_questions_in_quiz(quiz["quiz_id"])
        rows.append((quiz["quiz_id"], quiz["title"], quiz["timer"], q_count))
```

---

### `show_summary_panel()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def show_summary_panel(query, context, quiz_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT title, description, timer FROM quizzes WHERE quiz_id = ?", (quiz_id,))
    quiz_data = cursor.fetchone()
    
    if not quiz_data:
        await query.message.reply_text("❌ Error: Quiz data could not be retrieved.")
        conn.close()
        return
    
    title, description, timer = quiz_data
    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (quiz_id,))
    total_q = cursor.fetchone()
    conn.close()
```

**New (MongoDB):**
```python
async def show_summary_panel(query, context, quiz_id):
    # ✅ Get quiz from MongoDB
    quiz_data = await get_quiz(quiz_id)
    
    if not quiz_data:
        await query.message.reply_text("❌ Error: Quiz data could not be retrieved.")
        return
    
    title = quiz_data["title"]
    description = quiz_data["description"]
    timer = quiz_data["timer"]
    
    # ✅ Count questions
    total_q = await count_questions_in_quiz(quiz_id)
```

---

### `send_next_group_poll()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def send_next_group_poll(chat_id, context):
    game = GROUP_GAMES.get(chat_id)
    quiz_id = game["quiz_id"]
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT title, timer, negative_value FROM quizzes WHERE quiz_id = ?", (quiz_id,))
    quiz_data = cursor.fetchone()
    quiz_title, timer, negative_value = quiz_data
    
    cursor.execute("SELECT question_text, options, correct_answer, pre_message, explanation FROM questions WHERE quiz_id = ?", (quiz_id,))
    questions = cursor.fetchall()
    conn.close()
```

**New (MongoDB):**
```python
async def send_next_group_poll(chat_id, context):
    game = GROUP_GAMES.get(chat_id)
    quiz_id = game["quiz_id"]
    
    # ✅ Get quiz from MongoDB
    quiz_data = await get_quiz(quiz_id)
    quiz_title = quiz_data["title"]
    timer = quiz_data["timer"]
    negative_value = quiz_data["negative_value"]
    
    # ✅ Get all questions from MongoDB
    questions = await get_quiz_questions(quiz_id)
    
    # Restructure for compatibility
    questions_formatted = [
        (q["question_text"], json.dumps(q["options"]), q["correct_answer"], q["pre_message"], q["explanation"])
        for q in questions
    ]
    questions = questions_formatted
```

---

### `compile_group_leaderboard()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def compile_group_leaderboard(chat_id, context):
    game = GROUP_GAMES.get(chat_id)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT title, negative_value FROM quizzes WHERE quiz_id = ?", (game["quiz_id"],))
    quiz_data = cursor.fetchone()
    quiz_title = quiz_data[0]
    db_neg_multiplier = quiz_data[1]
    
    cursor.execute("SELECT question_text, options, correct_answer FROM questions WHERE quiz_id = ?", (game["quiz_id"],))
    questions = cursor.fetchall()
    conn.close()
```

**New (MongoDB):**
```python
async def compile_group_leaderboard(chat_id, context):
    game = GROUP_GAMES.get(chat_id)
    
    # ✅ Get quiz from MongoDB
    quiz_data = await get_quiz(game["quiz_id"])
    quiz_title = quiz_data["title"]
    db_neg_multiplier = quiz_data["negative_value"]
    
    # ✅ Get all questions from MongoDB
    questions = await get_quiz_questions(game["quiz_id"])
    
    # Restructure for compatibility
    questions_formatted = [
        (q["question_text"], json.dumps(q["options"]), q["correct_answer"])
        for q in questions
    ]
    questions = questions_formatted
```

---

### `edit_question_trigger()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def edit_question_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quiz_id = int(query.data.split("_")[1])
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, question_text FROM questions WHERE quiz_id = ?", (quiz_id,))
    questions = cursor.fetchall()
    conn.close()
```

**New (MongoDB):**
```python
async def edit_question_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quiz_id = int(query.data.split("_")[1])
    
    # ✅ Get questions from MongoDB
    questions_docs = await get_quiz_questions(quiz_id)
    questions = [(q["question_id"], q["question_text"]) for q in questions_docs]
```

---

### `show_question_detail_panel()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def show_question_detail_panel(query, context, quiz_id, question_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, question_text, options, correct_answer, explanation, pre_message FROM questions WHERE id = ? AND quiz_id = ?", (question_id, quiz_id))
    q_data = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id = ? AND id < ?", (quiz_id, question_id))
    q_number = cursor.fetchone()[0] + 1
    conn.close()
```

**New (MongoDB):**
```python
async def show_question_detail_panel(query, context, quiz_id, question_id):
    # ✅ Get question from MongoDB
    q_data_doc = await get_question(question_id)
    
    if not q_data_doc:
        await query.answer("❌ Question not found!", show_alert=True)
        return
    
    # Restructure to match old format
    q_data = (
        q_data_doc["question_id"],
        q_data_doc["question_text"],
        json.dumps(q_data_doc["options"]),
        q_data_doc["correct_answer"],
        q_data_doc["explanation"],
        q_data_doc["pre_message"]
    )
    
    # ✅ Get question number (index)
    all_questions = await get_quiz_questions(quiz_id)
    q_number = next((i+1 for i, q in enumerate(all_questions) if q["question_id"] == question_id), 1)
```

---

### `save_pre_message()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_pre_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q_id = context.user_data.get("editing_q_id")
    quiz_id = context.user_data.get("editing_quiz_id")
    text = update.message.text.strip()
    
    if not q_id or not quiz_id:
        await update.message.reply_text("❌ Error: Session expired.")
        return ConversationHandler.END
    
    new_pre_msg = "" if text.lower() == "/remove" else text
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE questions SET pre_message = ? WHERE id = ?", (new_pre_msg, q_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_pre_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q_id = context.user_data.get("editing_q_id")
    quiz_id = context.user_data.get("editing_quiz_id")
    text = update.message.text.strip()
    
    if not q_id or not quiz_id:
        await update.message.reply_text("❌ Error: Session expired.")
        return ConversationHandler.END
    
    new_pre_msg = "" if text.lower() == "/remove" else text
    
    # ✅ Update in MongoDB
    success = await update_question(q_id, pre_message=new_pre_msg)
    if not success:
        await update.message.reply_text("❌ Error saving pre-message.")
        return ConversationHandler.END
```

---

### `save_explanation()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q_id = context.user_data.get("editing_q_id")
    text = update.message.text.strip()
    
    new_explanation = "" if text.lower() == "/remove" else text
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE questions SET explanation = ? WHERE id = ?", (new_explanation, q_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q_id = context.user_data.get("editing_q_id")
    text = update.message.text.strip()
    
    new_explanation = "" if text.lower() == "/remove" else text
    
    # ✅ Update in MongoDB
    success = await update_question(q_id, explanation=new_explanation)
    if not success:
        await update.message.reply_text("❌ Error saving explanation.")
        return ConversationHandler.END
```

---

### `confirm_delete_question()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def confirm_delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    quiz_id = int(parts[1])
    question_id = int(parts[2])
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def confirm_delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    quiz_id = int(parts[1])
    question_id = int(parts[2])
    
    # ✅ Delete from MongoDB
    success = await delete_question(question_id)
    if not success:
        await query.answer("❌ Error deleting question", show_alert=True)
        return
```

---

### `save_edited_title()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_edited_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_title = update.message.text.strip()
    quiz_id = context.user_data.get("editing_quiz_id")
    
    if len(new_title) > 128:
        await update.message.reply_text("⚠️ This title is too long...")
        return EDIT_TITLE
    
    if not quiz_id:
        await update.message.reply_text("❌ Error: Session expired...")
        return ConversationHandler.END
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE quizzes SET title = ? WHERE quiz_id = ?", (new_title, quiz_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_edited_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_title = update.message.text.strip()
    quiz_id = context.user_data.get("editing_quiz_id")
    
    if len(new_title) > 128:
        await update.message.reply_text("⚠️ This title is too long...")
        return EDIT_TITLE
    
    if not quiz_id:
        await update.message.reply_text("❌ Error: Session expired...")
        return ConversationHandler.END
        
    # ✅ Update in MongoDB
    success = await update_quiz(quiz_id, title=new_title)
    if not success:
        await update.message.reply_text("❌ Error updating title. Please try again.")
        return EDIT_TITLE
```

---

### `save_edited_desc()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_edited_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    new_desc = "" if text.lower() == "/skip" else text
    quiz_id = context.user_data.get("editing_quiz_id")
    
    if not quiz_id:
        await update.message.reply_text("❌ Error: Session expired.")
        return ConversationHandler.END
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE quizzes SET description = ? WHERE quiz_id = ?", (new_desc, quiz_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_edited_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    new_desc = "" if text.lower() == "/skip" else text
    quiz_id = context.user_data.get("editing_quiz_id")
    
    if not quiz_id:
        await update.message.reply_text("❌ Error: Session expired.")
        return ConversationHandler.END
        
    # ✅ Update in MongoDB
    success = await update_quiz(quiz_id, description=new_desc)
    if not success:
        await update.message.reply_text("❌ Error updating description. Please try again.")
        return EDIT_DESC
```

---

### `save_edited_timer()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_edited_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    time_map = {"15": 15, "30": 30, "40": 40, "60": 60}
    
    if text not in time_map:
        await update.message.reply_text("❌ Invalid entry!...")
        return EDIT_TIMER
        
    quiz_id = context.user_data.get("editing_quiz_id")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE quizzes SET timer = ? WHERE quiz_id = ?", (time_map[text], quiz_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_edited_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    time_map = {"15": 15, "30": 30, "40": 40, "60": 60}
    
    if text not in time_map:
        await update.message.reply_text("❌ Invalid entry!...")
        return EDIT_TIMER
        
    quiz_id = context.user_data.get("editing_quiz_id")
    
    # ✅ Update in MongoDB
    success = await update_quiz(quiz_id, timer=time_map[text])
    if not success:
        await update.message.reply_text("❌ Error updating timer. Please try again.")
        return EDIT_TIMER
```

---

### `save_edited_negative()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def save_edited_negative(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    quiz_id = int(parts[1])
    new_neg_val = float(parts[2])
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE quizzes SET negative_value = ? WHERE quiz_id = ?", (new_neg_val, quiz_id))
    conn.commit()
    conn.close()
```

**New (MongoDB):**
```python
async def save_edited_negative(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    quiz_id = int(parts[1])
    new_neg_val = float(parts[2])
    
    # ✅ Update in MongoDB
    success = await update_quiz(quiz_id, negative_value=new_neg_val)
    if not success:
        await query.message.reply_text("❌ Error updating negative marking.")
        return EDIT_NEGATIVE
```

---

### `inline_query_handler()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id
    
    if not query:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT quiz_id, title, description, timer FROM quizzes WHERE creator_id = ? ORDER BY quiz_id DESC LIMIT 50", 
            (user_id,)
        )
        user_quizzes = cursor.fetchall()
        conn.close()
```

**New (MongoDB):**
```python
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id
    
    if not query:
        # ✅ Get quizzes from MongoDB
        user_quizzes_docs = await get_user_quizzes(user_id)
        user_quizzes = [
            (q["quiz_id"], q["title"], q["description"], q["timer"])
            for q in user_quizzes_docs
        ]
```

---

### `execute_broadcast_callback()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def execute_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    with sqlite3.connect(DB_FILE, timeout=20) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT chat_id FROM broadcast_groups")
            all_chats = cursor.fetchall()
        except Exception:
            all_chats = []
        try:
            cursor.execute("SELECT chat_id FROM broadcast_users")
            all_users = cursor.fetchall()
        except Exception:
            all_users = []
    
    # Convert to list of IDs
    all_chats = [row[0] for row in all_chats]
    all_users = [row[0] for row in all_users]
```

**New (MongoDB):**
```python
async def execute_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    # ✅ Get from MongoDB
    all_chats = await get_broadcast_groups()
    all_users = await get_broadcast_users()
    
    # Already lists of IDs, no need to convert
```

---

### `autorun_command()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def autorun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM autoruns WHERE quiz_id = ? AND active = 1", (quiz_id,))
        row = cur.fetchone()
        if row:
            autorun_id = row[0]
            cur.execute("UPDATE autoruns SET interval_minutes = ?, schedule_time = ? WHERE id = ?", (interval, schedule_time, autorun_id))
        else:
            cur.execute("INSERT INTO autoruns (quiz_id, interval_minutes, schedule_time) VALUES (?, ?, ?)", (quiz_id, interval, schedule_time))
            autorun_id = cur.lastrowid
        conn.commit()
```

**New (MongoDB):**
```python
async def autorun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    # ✅ Check if autorun exists
    existing_autorun = await get_autorun_by_quiz(quiz_id)
    if existing_autorun:
        autorun_id = existing_autorun["autorun_id"]
        await update_autorun(autorun_id, interval_minutes=interval, schedule_time=schedule_time)
    else:
        autorun_id = await create_autorun(quiz_id, interval, schedule_time)
```

---

### `stopautorun_command()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def stopautorun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        
        if key == "all":
            cur.execute("SELECT id FROM autoruns WHERE active = 1")
            active_autoruns = cur.fetchall()
            num_stopped = len(active_autoruns)
            
            cur.execute("UPDATE autoruns SET active = 0 WHERE active = 1")
            conn.commit()
```

**New (MongoDB):**
```python
async def stopautorun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... code ...
    
    if key == "all":
        # ✅ Get active autoruns from MongoDB
        active_autoruns = await get_active_autoruns()
        num_stopped = len(active_autoruns)
        
        for autorun in active_autoruns:
            await deactivate_autorun(autorun["autorun_id"])
```

---

### `load_autoruns_on_startup()` - MAJOR CHANGE
**Old (SQLite):**
```python
async def load_autoruns_on_startup(app):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, quiz_id, interval_minutes FROM autoruns WHERE active = 1")
            rows = cur.fetchall()
        for autorun_id, quiz_id, interval in rows:
            schedule_autorun_task(app, autorun_id, quiz_id, interval)
```

**New (MongoDB):**
```python
async def load_autoruns_on_startup(app):
    try:
        # ✅ Get active autoruns from MongoDB
        active_autoruns = await get_active_autoruns()
        for autorun in active_autoruns:
            schedule_autorun_task(
                app, 
                autorun["autorun_id"], 
                autorun["quiz_id"], 
                autorun["interval_minutes"]
            )
```

---

### `main()` - FINAL CHANGES
**Add at end of main() before app.run_polling():**

```python
async def main():
    # ... existing code ...
    
    try:
        # ✅ Initialize MongoDB instead of SQLite
        await init_mongodb()
        
        # ... rest of app setup ...
        
        # Load autoruns from MongoDB
        await load_autoruns_on_startup(app)
        
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            # ✅ Close MongoDB connection on shutdown
            await close_mongodb()
            await app.stop()
```

---

## ENVIRONMENT VARIABLES (.env)

Add these to your `.env` file:

```env
# MongoDB Configuration
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=quiz_bot

# Or local MongoDB
# MONGODB_URI=mongodb://localhost:27017
# MONGODB_DB_NAME=quiz_bot
```

---

## REQUIREMENTS.txt

Update dependencies:

```
python-telegram-bot==20.3
motor==3.3.1
pymongo==4.6.0
python-dotenv==1.0.0
aiohttp==3.9.0
httpx==0.25.0
google-genai==0.3.0
```

---

## TESTING CHECKLIST

- [ ] Bot starts without SQLite errors
- [ ] Quiz creation works and saves to MongoDB
- [ ] Quiz listing shows all quizzes from MongoDB
- [ ] Question editing/deletion works
- [ ] Broadcast functionality works with MongoDB users/groups
- [ ] Autorun tasks load and execute from MongoDB
- [ ] Group quizzes work with in-memory `GROUP_GAMES`
- [ ] Leaderboard calculation works correctly

---

## MIGRATION SUMMARY

**Removed:** All SQLite operations  
**Added:** Async MongoDB operations via `mongodb_config.py`  
**Unchanged:** Game logic, quiz flow, handler structure  
**Benefit:** Scalability, cloud-ready, better performance

