import asyncio
from telegram.ext import ConversationHandler, CallbackQueryHandler
from telegram.ext import ApplicationBuilder
import warnings

def main():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # default
        c1 = ConversationHandler(
            entry_points=[CallbackQueryHandler(lambda u, c: None)],
            states={1: []},
            fallbacks=[]
        )
        print("Default warnings:", len(w))
        
        w.clear()
        # explicit false
        c2 = ConversationHandler(
            entry_points=[CallbackQueryHandler(lambda u, c: None)],
            states={1: []},
            fallbacks=[],
            per_message=False
        )
        print("Explicit False warnings:", len(w))

if __name__ == '__main__':
    main()
