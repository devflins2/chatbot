import os
from app import create_app

# Load production configuration by default
env = os.environ.get("FLASK_ENV", "production")
application = create_app(env)

if __name__ == "__main__":
    application.run()
