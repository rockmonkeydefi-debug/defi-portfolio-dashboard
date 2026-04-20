"""CLI tool to set the app password. Generates a bcrypt hash and saves it to .env."""
import os
import getpass
import bcrypt
from dotenv import set_key

def main():
    pw = getpass.getpass("Enter new password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        print("Passwords don't match.")
        return
    if len(pw) < 6:
        print("Password must be at least 6 characters.")
        return
    
    pw_hash = bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    env_file = os.getenv("DOTENV_PATH", ".env")
    set_key(env_file, "APP_PASSWORD_HASH", pw_hash)
    print(f"Password hash saved to {env_file}")
    print("Restart the app for changes to take effect.")

if __name__ == "__main__":
    main()
