# main.py
# This is the main file that we use to run our project.
# Think of it like the "front door" to your program.
# We'll use this to test the other modules like scraper, parser, downloader, etc.

# --- IMPORTING LIBRARIES AND MODULES ---

# This imports the 'scraper' module from the 'modules' folder
# The scraper is the part of the program that gets the webpage HTML from a manga website
from modules import scraper

# We'll add other modules like 'parser', 'downloader', etc. as we build them
# For now, we're just testing the scraper


# --- MAIN FUNCTION ---
# This is the main function that runs when we start the program
def main():
    # Ask the user to enter a manga URL
    # For example: https://somesite.com/manga-title/
    url = input("Enter the manga URL: ")

    # Use the scraper module to fetch the HTML from that URL
    # This part talks to the internet and gets the webpage code (HTML)
    print("\nFetching HTML content...")

    try:
        html = scraper.fetch_page(url)  # Calls the fetch_page function from scraper.py

        # If it works, show the first 500 characters of the HTML to confirm it's working
        print("\n--- HTML Preview (First 500 characters) ---")
        print(html[:500])  # Just a sneak peek so it doesn't flood the screen
        print("\n✅ Success! The page was fetched correctly.")

    except Exception as e:
        # If there's a problem (like a bad URL or connection error), show the error
        print("\n❌ Oops! Something went wrong while trying to fetch the page:")
        print(str(e))


# --- RUN THE MAIN FUNCTION ---

# This tells Python to run our 'main' function when we start this script
# It's like saying: "Hey, start the program here!"
if __name__ == "__main__":
    main()
