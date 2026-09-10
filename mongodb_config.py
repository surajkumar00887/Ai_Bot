"""
MongoDB Configuration and Helper Functions for Quiz Bot
Replaces SQLite database operations
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, UNIQUE

# 🇮🇳 India Standard Time (IST) Timezone
IST = timezone(timedelta(hours=5, minutes=30))

# MongoDB Connection URI from environment
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "quiz_bot")

# Global async MongoDB client
mongo_client = None
mongo_db = None

async def init_mongodb():
    """Initialize MongoDB connection and create collections"""
    global mongo_client, mongo_db
    
    try:
        # Create async motor client
        mongo_client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        
        # Verify connection
        await mongo_client.admin.command('ping')
        logging.info("✅ MongoDB connected successfully")
        
        # Get database reference
        mongo_db = mongo_client[MONGODB_DB_NAME]
        
        # Create collections with indexes
        await create_collections_and_indexes()
        
        return mongo_db
    except Exception as e:
        logging.error(f"❌ MongoDB connection failed: {e}")
        raise

async def create_collections_and_indexes():
    """Create MongoDB collections and set up indexes"""
    try:
        # Collection: quizzes
        if "quizzes" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("quizzes")
        
        await mongo_db.quizzes.create_index("quiz_id", unique=True)
        await mongo_db.quizzes.create_index("creator_id")
        logging.info("✅ Quizzes collection initialized")
        
        # Collection: questions
        if "questions" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("questions")
        
        await mongo_db.questions.create_index("quiz_id")
        await mongo_db.questions.create_index("question_id", unique=True)
        logging.info("✅ Questions collection initialized")
        
        # Collection: broadcast_users
        if "broadcast_users" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("broadcast_users")
        
        await mongo_db.broadcast_users.create_index("chat_id", unique=True)
        logging.info("✅ Broadcast users collection initialized")
        
        # Collection: broadcast_groups
        if "broadcast_groups" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("broadcast_groups")
        
        await mongo_db.broadcast_groups.create_index("chat_id", unique=True)
        logging.info("✅ Broadcast groups collection initialized")
        
        # Collection: autoruns
        if "autoruns" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("autoruns")
        
        await mongo_db.autoruns.create_index("quiz_id")
        await mongo_db.autoruns.create_index("autorun_id", unique=True)
        logging.info("✅ Autoruns collection initialized")
        
        # Collection: sequences (for auto-incrementing IDs)
        if "sequences" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("sequences")
            # Initialize sequences for each collection
            await mongo_db.sequences.insert_many([
                {"_id": "quiz_id", "seq": 0},
                {"_id": "question_id", "seq": 0},
                {"_id": "autorun_id", "seq": 0}
            ])
        logging.info("✅ Sequences collection initialized")
        
    except Exception as e:
        logging.error(f"Error creating collections and indexes: {e}")
        raise

async def get_next_sequence(seq_name):
    """Get next auto-increment ID for a collection"""
    try:
        result = await mongo_db.sequences.find_one_and_update(
            {"_id": seq_name},
            {"$inc": {"seq": 1}},
            return_document=True
        )
        return result["seq"] if result else 1
    except Exception as e:
        logging.error(f"Error getting next sequence for {seq_name}: {e}")
        return None

async def close_mongodb():
    """Close MongoDB connection"""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logging.info("✅ MongoDB connection closed")

# =====================================================================
# QUIZ OPERATIONS
# =====================================================================

async def create_quiz(creator_id, title, description, timer=30, negative_value=0.0):
    """Create a new quiz"""
    try:
        quiz_id = await get_next_sequence("quiz_id")
        
        quiz_doc = {
            "quiz_id": quiz_id,
            "creator_id": creator_id,
            "title": title,
            "description": description,
            "timer": timer,
            "negative_value": negative_value,
            "created_at": datetime.now(tz=IST),
            "updated_at": datetime.now(tz=IST)
        }
        
        await mongo_db.quizzes.insert_one(quiz_doc)
        logging.info(f"✅ Quiz created: ID={quiz_id}, Title={title}")
        return quiz_id
    except Exception as e:
        logging.error(f"Error creating quiz: {e}")
        return None

async def get_quiz(quiz_id):
    """Get quiz details by ID"""
    try:
        quiz = await mongo_db.quizzes.find_one({"quiz_id": quiz_id})
        return quiz
    except Exception as e:
        logging.error(f"Error fetching quiz {quiz_id}: {e}")
        return None

async def get_user_quizzes(creator_id):
    """Get all quizzes created by a user"""
    try:
        quizzes = await mongo_db.quizzes.find(
            {"creator_id": creator_id}
        ).sort("quiz_id", DESCENDING).to_list(length=None)
        return quizzes
    except Exception as e:
        logging.error(f"Error fetching user quizzes: {e}")
        return []

async def update_quiz(quiz_id, **updates):
    """Update quiz details"""
    try:
        updates["updated_at"] = datetime.now(tz=IST)
        result = await mongo_db.quizzes.update_one(
            {"quiz_id": quiz_id},
            {"$set": updates}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"Error updating quiz {quiz_id}: {e}")
        return False

async def delete_quiz(quiz_id):
    """Delete a quiz and all its questions"""
    try:
        # Delete questions
        await mongo_db.questions.delete_many({"quiz_id": quiz_id})
        # Delete quiz
        result = await mongo_db.quizzes.delete_one({"quiz_id": quiz_id})
        return result.deleted_count > 0
    except Exception as e:
        logging.error(f"Error deleting quiz {quiz_id}: {e}")
        return False

# =====================================================================
# QUESTION OPERATIONS
# =====================================================================

async def create_question(quiz_id, question_text, options, correct_answer, explanation="", pre_message=""):
    """Create a new question"""
    try:
        question_id = await get_next_sequence("question_id")
        
        question_doc = {
            "question_id": question_id,
            "quiz_id": quiz_id,
            "question_text": question_text,
            "options": options,
            "correct_answer": correct_answer,  # INTEGER INDEX
            "explanation": explanation,
            "pre_message": pre_message,
            "created_at": datetime.now(tz=IST),
            "updated_at": datetime.now(tz=IST)
        }
        
        await mongo_db.questions.insert_one(question_doc)
        logging.info(f"✅ Question created: ID={question_id}, Quiz={quiz_id}")
        return question_id
    except Exception as e:
        logging.error(f"Error creating question: {e}")
        return None

async def get_quiz_questions(quiz_id):
    """Get all questions for a quiz"""
    try:
        questions = await mongo_db.questions.find(
            {"quiz_id": quiz_id}
        ).sort("question_id", ASCENDING).to_list(length=None)
        return questions
    except Exception as e:
        logging.error(f"Error fetching questions for quiz {quiz_id}: {e}")
        return []

async def get_question(question_id):
    """Get a specific question"""
    try:
        question = await mongo_db.questions.find_one({"question_id": question_id})
        return question
    except Exception as e:
        logging.error(f"Error fetching question {question_id}: {e}")
        return None

async def update_question(question_id, **updates):
    """Update question details"""
    try:
        updates["updated_at"] = datetime.now(tz=IST)
        result = await mongo_db.questions.update_one(
            {"question_id": question_id},
            {"$set": updates}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"Error updating question {question_id}: {e}")
        return False

async def delete_question(question_id):
    """Delete a question"""
    try:
        result = await mongo_db.questions.delete_one({"question_id": question_id})
        return result.deleted_count > 0
    except Exception as e:
        logging.error(f"Error deleting question {question_id}: {e}")
        return False

# =====================================================================
# BROADCAST OPERATIONS
# =====================================================================

async def add_broadcast_user(chat_id):
    """Add user to broadcast list"""
    try:
        await mongo_db.broadcast_users.update_one(
            {"chat_id": chat_id},
            {"$set": {"chat_id": chat_id, "added_at": datetime.now(tz=IST)}},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Error adding broadcast user: {e}")

async def add_broadcast_group(chat_id):
    """Add group to broadcast list"""
    try:
        await mongo_db.broadcast_groups.update_one(
            {"chat_id": chat_id},
            {"$set": {"chat_id": chat_id, "added_at": datetime.now(tz=IST)}},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Error adding broadcast group: {e}")

async def get_broadcast_users():
    """Get all users in broadcast list"""
    try:
        users = await mongo_db.broadcast_users.find().to_list(length=None)
        return [doc["chat_id"] for doc in users]
    except Exception as e:
        logging.error(f"Error fetching broadcast users: {e}")
        return []

async def get_broadcast_groups():
    """Get all groups in broadcast list"""
    try:
        groups = await mongo_db.broadcast_groups.find().to_list(length=None)
        return [doc["chat_id"] for doc in groups]
    except Exception as e:
        logging.error(f"Error fetching broadcast groups: {e}")
        return []

# =====================================================================
# AUTORUN OPERATIONS
# =====================================================================

async def create_autorun(quiz_id, interval_minutes, schedule_time=None):
    """Create a new autorun"""
    try:
        autorun_id = await get_next_sequence("autorun_id")
        
        autorun_doc = {
            "autorun_id": autorun_id,
            "id": autorun_id,  # Keep for compatibility
            "quiz_id": quiz_id,
            "interval_minutes": interval_minutes,
            "schedule_time": schedule_time,
            "next_run": None,
            "active": 1,
            "created_at": datetime.now(tz=IST),
            "updated_at": datetime.now(tz=IST)
        }
        
        await mongo_db.autoruns.insert_one(autorun_doc)
        logging.info(f"✅ Autorun created: ID={autorun_id}, Quiz={quiz_id}")
        return autorun_id
    except Exception as e:
        logging.error(f"Error creating autorun: {e}")
        return None

async def get_active_autoruns():
    """Get all active autoruns"""
    try:
        autoruns = await mongo_db.autoruns.find({"active": 1}).to_list(length=None)
        return autoruns
    except Exception as e:
        logging.error(f"Error fetching active autoruns: {e}")
        return []

async def update_autorun(autorun_id, **updates):
    """Update autorun details"""
    try:
        updates["updated_at"] = datetime.now(tz=IST)
        result = await mongo_db.autoruns.update_one(
            {"autorun_id": autorun_id},
            {"$set": updates}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"Error updating autorun {autorun_id}: {e}")
        return False

async def deactivate_autorun(autorun_id):
    """Deactivate an autorun"""
    try:
        result = await mongo_db.autoruns.update_one(
            {"autorun_id": autorun_id},
            {"$set": {"active": 0, "updated_at": datetime.now(tz=IST)}}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"Error deactivating autorun {autorun_id}: {e}")
        return False

async def get_autorun_by_quiz(quiz_id):
    """Get autorun by quiz ID"""
    try:
        autorun = await mongo_db.autoruns.find_one({"quiz_id": quiz_id, "active": 1})
        return autorun
    except Exception as e:
        logging.error(f"Error fetching autorun for quiz {quiz_id}: {e}")
        return None

# =====================================================================
# COUNT OPERATIONS
# =====================================================================

async def count_questions_in_quiz(quiz_id):
    """Count questions in a quiz"""
    try:
        count = await mongo_db.questions.count_documents({"quiz_id": quiz_id})
        return count
    except Exception as e:
        logging.error(f"Error counting questions: {e}")
        return 0

async def count_user_quizzes(creator_id):
    """Count quizzes by user"""
    try:
        count = await mongo_db.quizzes.count_documents({"creator_id": creator_id})
        return count
    except Exception as e:
        logging.error(f"Error counting user quizzes: {e}")
        return 0
