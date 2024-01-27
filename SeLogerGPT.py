import json
import os
import random
import re
import time

import dotenv
import openai
import requests
from parsel import Selector
from scrapfly import ScrapeConfig, ScrapflyClient
from telegram import Bot
from telegram.error import RetryAfter, TimedOut

# Import search parameters and criteria from the search_config module
from search_config import (
    PROJECT_BUY_EXISTING,
    MANDATORY_COMMODITIES,
    natures, 
    insee_codes,
    price_min,
    price_max,
    surface_min,
    surface_max,
    bedrooms,
    garden,
    CRITERES_INTERESSANTS,
)

#################   CONFIGURATION   #################
# State restoration files
PROCESSED_ANNOUNCEMENTS_FILE = 'processed_urls.json' # File to load and save processed URLs
RESULTS_FILE = 'announcement_results.json'  # File to load and save page description

# Constants for easy changes
BASE_URL = "https://www.seloger.com"
ANNOUNCEMENT_URL_SELECTOR = 'a[data-testid="sl.explore.coveringLink"]::attr(href)'

QUARTIER_SELECTOR = 'props.pageProps.listingData.listing.listingDetail.address'
DESCRIPTION_SELECTOR = 'props.pageProps.listingData.listing.listingDetail.descriptive'
ADDITIONAL_INFO_SELECTOR = 'props.pageProps.listingData.listing.listingDetail.featureCategories'
IMAGE_SELECTOR = 'props.pageProps.listingData.listing.listingDetail.media.photos[0].originalUrl'


# Telegram bot configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')  # Your personal chat id or a group chat id where the bot is added.
MAX_CAPTION_LENGTH = 1024
RETRY_DELAY = 5  # seconds to wait before retrying
MAX_RETRIES = 5  # maximum number of retries
tg_bot = Bot(token=TELEGRAM_BOT_TOKEN)

# OpenAI API configuration
openai.api_key = os.getenv('OPENAI_API_KEY')
GPT_MODEL = "gpt-4-1106-preview"

# Scrapfly API configuration
SCRAPFLY_API_KEY = os.getenv('SCRAPFLY_API_KEY')

dotenv.load_dotenv()

############ State restoration management ############
# Function to save results to a file
def save_results(data):
    """
    Save the given data to a file in JSON format.

    The RESULTS_FILE global variable should contain the file path where
    the data will be saved. This function opens that file in write mode
    and writes the data as JSON.

    Args:
        data: The data to be saved. It must be serializable by the json module.

    Returns:
        None
    """
    with open(RESULTS_FILE, 'w') as file:
        json.dump(data, file)

# Function to load results from a file
def load_results():
    """
    Load results from a JSON file.

    This function attempts to open a file specified by the constant RESULTS_FILE,
    parse its JSON content, and return the resulting dictionary. If the file does
    not exist, or if an error occurs during parsing (e.g., due to invalid JSON), 
    the function will return an empty dictionary.
    Returns:
        dict: A dictionary containing the parsed JSON data, or an empty dictionary
              if the file does not exist or the JSON is invalid.
    """
    try:
        with open(RESULTS_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}  # Return an empty dictionary if file does not exist or is empty/corrupt

# Load processed URLs from a file
def load_processed_announcements(file_path):
    """
    Load a set of processed announcement URLs from the specified file.
    
    This function attempts to read a file containing JSON data and converts
    it into a set of URLs. If the file cannot be read or the JSON data is
    malformed, an empty set is returned instead.
    
    Parameters:
    - file_path (str): The path to the file containing the processed URLs in JSON format.
    Returns:
    - set: A set containing the processed URLs, or an empty set if the file cannot be
           read or the JSON content cannot be decoded.
    """
    try:
        with open(file_path, 'r') as file:
            return set(json.load(file))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

# Save processed URLs to a file
def save_processed_announcements(file_path, processed_announcements):
    """
    Save a list of processed announcement IDs to a file in JSON format.

    :param file_path: The path of the file where the processed announcement IDs will be stored.
    :param processed_announcements: A set or list of processed announcement IDs to be saved.
    """
    with open(file_path, 'w') as file:
        json.dump(list(processed_announcements), file)

def should_process_announcement(annonce_id, processed_announcements):
    """
    Determine whether an announcement ID has not been processed yet.

    :param annonce_id: The ID of the announcement to check.
    :param processed_announcements: A set or list of IDs that have already been processed.
    :return: True if the announcement ID has not been processed, False otherwise.
    """
    return annonce_id not in processed_announcements

############## Telegram bot management ###############
def create_message(url: str, data: dict) -> str:
    """
    Constructs a formatted message with a title, URL, and description obtained from the input data.

    Parameters:
    - url (str): The URL to be included in the message.
    - data (dict): Data containing the 'titre' (title) and 'resume' (description) for the message.
    Returns:
    - str: A string containing the formatted message.
    """
    message = f"Title: {data['titre']}\nURL: {url}\n"
    message += f"Description:\n{data['resume']}\n"
    return message

async def send_telegram_message(bot, message: str):
    """
    Attempts to send a Telegram message with retries on failure due to rate limits or timeouts.

    Parameters:
    - bot: The Telegram bot instance to send messages with.
    - message (str): The message text to be sent.

    Exceptions:
    - RetryAfter: If rate limits are exceeded, the bot waits and retries as indicated.
    - TimedOut: If a timeout occurs, the bot will retry until max retries are exceeded.
    """
    for attempt in range(MAX_RETRIES):
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')  # Use await
            break  # Message sent successfully
        except RetryAfter as e:
            print(f"Rate limit exceeded, sleeping for {e.retry_after} seconds")
            time.sleep(e.retry_after)
        except TimedOut:
            if attempt < MAX_RETRIES - 1:  # Don't sleep after the last attempt
                time.sleep(RETRY_DELAY)
            else:
                print('Failed to send Telegram message after retries')

async def send_telegram_info(bot, annonce_id: str, data: dict):
    """
    Sends a formatted Telegram message with or without an image based on the provided data.

    Parameters:
    - bot: The Telegram bot instance to send messages with.
    - annonce_id (str): The announcement id, not currently used in this function.
    - data (dict): Data containing the necessary information for constructing the message.
                   Expected keys include 'url', 'titre', 'resume', and optionally 'img'.

    Exceptions:
    - TimedOut: If a timeout occurs, the bot will retry until max retries are exceeded.
    """
    message = create_message(data['url'], data)
    for attempt in range(MAX_RETRIES):
        try:
            if data.get('img'):  # If image is provided in data
                if data['img'] != 'Unknown image':
                    with open(data['img'], 'rb') as photo:
                        await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=photo, caption=f"Title: {data['titre']}", parse_mode='Markdown')  # Use await
                # Call the async function with await
                await send_telegram_message(bot, message)  # Send the rest of the message as text
            else:
                # Call the async function with await
                await send_telegram_message(bot, message)  # If no image, only send text message
            break  # Message sent successfully
        except TimedOut:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                print('Failed to send Telegram info after retries')


###################### Helpers #######################
def create_search_url(projects, types, natures, insee_codes, price_min, price_max, surface_min, surface_max, bedrooms, mandatorycommodities, garden):
    base_url = "https://www.seloger.com/list.htm?"
    places = json.dumps([{"inseeCodes": [insee_codes]}])
    params = {
        "projects": projects,
        "types": types,
        "natures": natures,
        "places": places,
        "price": f"{price_min}/{price_max}",
        "surface": f"{surface_min}/{surface_max}",
        "bedrooms": bedrooms,
        "sort": "d_dt_crea",
        "mandatorycommodities": mandatorycommodities,
        "enterprise": 0,
        # "garden": garden,
        "qsVersion": "1.0",
        "m": "search_refine-redirection-search_results"
    }
    return base_url + "&".join([f"{k}={v}" for k, v in params.items()])

def get_total_announcements(title):
    total_announcements_match = re.search(r'(\d+) annonces', title)
    if not total_announcements_match:
        print("Could not determine the total number of announcements from the title")
        return 0
    return int(total_announcements_match.group(1))

def get_value_from_json_path(data, path: str):
    try:
        elements = path.split('.')
        for elem in elements:
            if '[' in elem and ']' in elem:
                # Handle list index within the path
                elem, index = elem.replace(']', '').split('[')
                data = data.get(elem)[int(index)]
            else:
                data = data.get(elem)
        return data
    except (IndexError, KeyError, TypeError):
        return None

def download_image(image_url):
    response = requests.get(image_url)
    if response.status_code == 200:
        file_name = f"img/{os.path.basename(image_url)}.jpg"
        with open(file_name, 'wb') as f:
            f.write(response.content)
        return file_name
    return None

def clean_text(text):
    return ' '.join(text.split())

def extract_announcement_id(url):
    match = re.search(r'/(\d+)\.htm', url)
    return match.group(1) if match else None



############## Anouncements management ###############
# Main parser function
async def parse_announcements(announcements_data: dict) -> dict:
    """
    Parse a dictionary of announcements, ask GPT for insights and send the info through Telegram.

    The function iterates through the given announcement data, checks if the announcement
    has already been processed, and if not, it uses the GPT to analyze the announcement.
    If the result is marked 'interessante', it sends the information through Telegram.
    All processed announcement IDs are stored to avoid reprocessing.

    Args:
        announcements_data (dict): A dictionary with announcement IDs as keys and data as values.

    Returns:
        dict: A dictionary of processed announcements.
    """
    items_to_parse = announcements_data.items()
    processed_announcements = load_processed_announcements(PROCESSED_ANNOUNCEMENTS_FILE)

    for annonce_id, details in items_to_parse:
        if should_process_announcement(annonce_id, processed_announcements):
            print(f"Asking GPT about {annonce_id}")
            result = ask_gpt(details['description'], details['additional_info'], details['image'], details['url'])
            if result.get('interessante'):
                await send_telegram_info(bot=tg_bot, annonce_id=annonce_id, data=result)
            processed_announcements.add(annonce_id)
        else:
            print(f"Skipping {annonce_id}")

    save_processed_announcements(PROCESSED_ANNOUNCEMENTS_FILE, processed_announcements)

# Function to get the URLs of all announcements
def get_announcement_urls(scrapfly_client, start_url, announcements_per_page=25):
    """
    Retrieves a list of URLs for real estate announcements from a paginated search result on a website.

    This function uses the Scrapfly API Client to scrape the provided `start_url` for real estate announcement URLs,
    then automatically follows pagination links to scrape subsequent pages until all announcement URLs have been 
    gathered up to the total number of announcements. It calculates the total number of pages based on the number
    of total announcements and the number of announcements per page, then iterates through all pages to extract
    and compile announcement URLs from the `ANNOUNCEMENT_URL_SELECTOR`.

    Args:
        scrapfly_client (ScrapflyClient): An instance of the ScrapflyClient used to scrape web content.
        start_url (str): The URL where the search starts, usually the first page of search results.
        announcements_per_page (int, optional): The number of announcements expected on each page. Defaults to 25.

    Returns:
        list: A list of strings, each being a complete URL to an individual real estate announcement.

    Note:
        If scraping a page fails, the function prints an error message and continues to the next page.
        URLs are normalized to remove query strings and ensure they are absolute and start with HTTP(S).
    """
    announcement_urls = []
    current_url = start_url
    print(f"Scraping page 1: {current_url}")

    # Fetch the first page to get the total number of announcements
    first_page_result = scrapfly_client.scrape(ScrapeConfig(
        url=current_url,
        asp=True,
        render_js=True,
        auto_scroll=True
    ))
    if not first_page_result.success:
        print(f"Error retrieving the first page: {first_page_result.error}")
        return announcement_urls

    first_page_selector = Selector(text=first_page_result.content)
    
    # Extract the initial set of URLs from the first page
    links = first_page_selector.css(ANNOUNCEMENT_URL_SELECTOR).getall()
    announcement_urls += [
        BASE_URL + link.split('?')[0] if not link.startswith('http')
        else link.split('?')[0] for link in links
    ]

    # Get the total number of announcements from the title to calculate total pages
    title = first_page_selector.css('title::text').get()
    total_announcements = get_total_announcements(title)
    total_pages = -(-total_announcements // announcements_per_page)  # Ceiling division
    print(f"Total announcements: {total_announcements}, total pages: {total_pages}")
    
    # Scrape subsequent pages
    for page_number in range(2, total_pages + 1):
        current_url = f"{start_url}&LISTING-LISTpg={page_number}"
        print(f"Scraping page {page_number}/{total_pages}: {current_url}")

        result = scrapfly_client.scrape(ScrapeConfig(
            url=current_url,
            asp=True,
            render_js=True,
            auto_scroll=True
        ))

        if not result.success:
            print(f"Error retrieving page {page_number}: {result.error}")
            continue

        selector = Selector(text=result.content)
        links = selector.css(ANNOUNCEMENT_URL_SELECTOR).getall()
        announcement_urls += [
            BASE_URL + link.split('?')[0] if not link.startswith('http')
            else link.split('?')[0] for link in links
        ]

    return announcement_urls

# Function to get the details for a single announcement
def get_announcement_details(scrapfly_client: ScrapflyClient, url: str):
    """
    Retrieves and processes details from an announcement at the given URL using the ScrapflyClient.
    
    The function attempts to scrape the specified webpage for details such as the quartier,
    description, additional info, and an image. These details are extracted from the JSON
    data within the webpage, if available. Furthermore, the image, if found, is downloaded
    and saved locally in the 'img' directory, which is ensured to exist before downloading.
    
    :param scrapfly_client: An instance of ScrapflyClient used to scrape web content.
    :param url: A string URL of the webpage where the announcement details can be found.
    :return: A dictionary with the extracted announcement details, including an ID,
             URL, combined description and quartier, additional info, and an image path.
             If certain details are not found, default placeholder values are used.
    """
    # Default values in case information is not found
    quartier = "Unknown quartier"
    description = "Description not found"
    additional_info = "Additional info not found"
    image_relative_path = 'Unknown image'

    # Ensure 'img' directory exists
    if not os.path.exists('img'):
        os.makedirs('img')

    try:
        # Scrape the announcement page
        result = scrapfly_client.scrape(ScrapeConfig(
            url=url,
            asp=True,
            render_js=True,
        ))

        # Check if the scrape was successful
        if not result.success:
            print(f"Failed to scrape announcement details from {url}")
            return None

        # Use Parsel to parse the HTML content
        selector = Selector(text=result.content)

        # Extract the JSON data from the script tag
        json_data = selector.css('script#__NEXT_DATA__::text').get()
        if json_data:
            data = json.loads(json_data)  # Parse JSON string into Python dictionary

            # Use new helper function to traverse the JSON structure
            quartier = get_value_from_json_path(data, QUARTIER_SELECTOR)
            description = get_value_from_json_path(data, DESCRIPTION_SELECTOR)
            additional_info = get_value_from_json_path(data, ADDITIONAL_INFO_SELECTOR)
            
            # If 'additional_info' is a data structure, convert it to string as needed
            if isinstance(additional_info, (list, dict)):
                additional_info = clean_text(str(additional_info))

            image_url_path = get_value_from_json_path(data, IMAGE_SELECTOR)
            if image_url_path:
                image_relative_path = download_image(image_url_path)

        else:
            print(f"No JSON data found on page {url}")

    except Exception as e:
        print(f"An error occurred while trying to get details from {url}: {e}")

    return {
        'id': extract_announcement_id(url),
        'url': url,
        'description': f"{quartier} - {description}",
        'additional_info': additional_info,
        'image': image_relative_path  # This should now contain the path where the image was saved or 'Unknown image'
    }

# Function to get the data for all announcements
def get_announcements_data():
    """
    Retrieve and process data for new real estate announcements from a given search URL.
    
    This function generates a search URL using predefined criteria and then scrapes SeLoger.com
    to obtain URLs of individual real estate announcements. For each announcement that hasn't 
    been processed previously, the function scrapes detailed data such as location, description,
    additional information, and images using the Scrapfly API. The data is stored in a dictionary
    keyed by the unique announcement IDs, and the dictionary is then saved to a file. The function
    checks each URL to ensure it originates from SeLoger.com before processing.

    Returns:
        dict: A dictionary containing detailed data for each announcement keyed by their IDs.
    """
    announcements_info = load_results()  # Load existing results
    scrapfly_client = ScrapflyClient(key=SCRAPFLY_API_KEY)
    
    url = create_search_url(
        projects=PROJECT_BUY_EXISTING,
        types=PROJECT_BUY_EXISTING,
        natures=natures,
        insee_codes=insee_codes,
        price_min=price_min,
        price_max=price_max,
        surface_min=surface_min,
        surface_max=surface_max,
        bedrooms=bedrooms,
        mandatorycommodities=MANDATORY_COMMODITIES,
        garden=garden
    )
    print(url)

    announcement_urls = get_announcement_urls(scrapfly_client, url, announcements_per_page=25)

    for url in announcement_urls:
        annonce_id = extract_announcement_id(url)
        if annonce_id not in announcements_info:
            if url.startswith('https://www.seloger.com'):
                print(f"Getting details for {url}")
                details = get_announcement_details(scrapfly_client, url)
                announcements_info[annonce_id] = details
            else:
                print(f"Skipping non-seloger URL: {url}")
    save_results(announcements_info)  # Save updated results
    return announcements_info



##################### GPT ############################
def ask_gpt(description: str, additional_info: str, img: str, url: str) -> dict:
    """
    Consult GPT-4 to analyze a real estate announcement and determine if it meets certain criteria.

    This function formats a prompt to ask GPT-4 if a given real estate announcement is interesting based on 
    the description, additional information provided, and a list of interesting criteria predefined in the software. 
    If the criteria marked as 'PAS' are in the announcement, it is immediately considered not interesting.

    If GPT-4 deems the announcement as interesting, it is asked to provide a summary with specific formatting including 
    details such as price, area, number of rooms, and general condition of the property.

    Args:
        description (str): The description of the real estate property.
        additional_info (str): Additional information that might be considered to evaluate the property.
        img (str): The image URL or path representing the property (if any).
        url (str): The URL of the announcement.

    Returns:
        dict: A dictionary containing the title of the announcement, a boolean indicating if it is interesting or not, 
              a summary provided by GPT-4, and the image path or URL. If GPT-4 cannot properly parse or interpret 
              the information, default values for titles and summaries are returned indicating that the property is 
              not interesting and the description is not found.

    Raises:
        json.JSONDecodeError: If the response from GPT-4 cannot be decoded.
        KeyError: If the necessary keys are not present in GPT-4's response.
    """
    if description is None:
        return {
            'titre': 'Titre non trouvé',
            'interessante': False,
            'resume': 'Description non trouvée',
            'img': img
        }
    # Formulation de la prompt pour GPT-4
    prompt = (f"Voici une description d'une annonce immobilière: {description}\n\n"
              f"Informations supplémentaires : {additional_info}\n\n"
              f"Critères intéressants : {', '.join(CRITERES_INTERESSANTS)}. ATTENTION : si un critère est marqué PAS, l'annonce devient immédiatement non intéressante.\n\n"
              'Est-ce que cette annonce répond à ces critères ? Formate ta réponse de la façon suivante : {"Interessante": true/false, "Titre": "Titre annonce"}. Il est absolument crucial que tu ne me répondes qu\'avec cette structure, sinon je ne pourrai pas comprendre ta réponse.')
              
    # Envoie la prompt à GPT-4 et reçoit la réponse
    response = openai.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": "Tu es un agent immobilier qui reçoit une description d'une annonce immobilière. Tu dois décider si cette annonce est intéressante ou non."},
            {"role": "user", "content": prompt},
        ]
    )
    
    # Assurez-vous que 'response' a le format correct pour accéder aux données
    try:
        texte_reponse = json.loads(response.choices[0].message.content)  # Fix the access to the response data
    except (json.JSONDecodeError, KeyError):
        print(f"Failed to parse response from GPT-4: {response}")
        return {
            'titre': 'Titre non trouvé',
            'interessante': False,
            'resume': 'Description non trouvée',
            'img': img
        }
    
    # Évaluer ici si les critères intéressants sont présents
    est_interessante = texte_reponse.get("Interessante", False)

    # Demandez un résumé si l'annonce est intéressante
    resume = ""
    if est_interessante:
        print("Annonce intéressante, génération du résumé")
        prompt_resume = (f"Donne-moi un résumé pertinent (prix, superficie, nombre de chambres, état général, critères, etc.) sous forme de bullet-point, formaté avec bold et italic, de cette annonce immobilière: {description}\n\n"
                         f"Informations supplémentaires : {additional_info}\n\n"
                         """
Le format attendu pour le résumé est le suivant :
**Localisation**
- Quartier: [Nom du quartier], Angers ([code postal])
- Proximité: [Eléments notables de l'environnement immédiat]

**Détails du bien**
- Type de bien: [Maison/Maison de ville/Appartement/etc.]
- Prix: [Prix] € ([Détails des honoraires si applicable])
- Superficie habitable: [Superficie habitable] m²
- Superficie du terrain: [Superficie du terrain] m²

**Disposition**
- Nombre de pièces: [Nombre total]
- Cuisine: [Description de la cuisine]
- Séjour: [Description et superficie]
- Chambres: [Nombre de chambres] (+ [Nombre de bureaux/salles de jeux si applicable])
- Salles d'eau: [Nombre de salles de bain + caractéristiques]
- WC: [Nombre de WC]
- Annexes: [Liste des annexes telles que jardin, garage, cave, etc.]

**Caractéristiques**
- État général: [État général du bien]
- Année de construction: [Année]
- Chauffage: [Type de chauffage]
- Équipements spéciaux: [Tout équipement spécial ou additionnel]
- Exposition: [Exposition si applicable]

**Diagnostics énergétiques**
- DPE (Diagnostic de Performance Énergétique): [Classe énergétique]
- GES (Émission de Gaz à Effet de Serre): [Classe climatique]

**Informations complémentaires**
- [Toute autre information intéressante sur le bien]
- [Informations sur les risques si disponibles]
                         """)
        response_resume = openai.chat.completions.create(
            model="gpt-4-1106-preview", 
            messages=[
                {"role": "system", "content": "Tu es un agent immobilier qui reçoit une description d'une annonce immobilière. Tu dois donner un résumé pertinent de cette annonce."},
                {"role": "user", "content": prompt_resume},
                ]
            )
        resume = response_resume.choices[0].message.content  # Fix the access to the response data

    return {
        'titre': texte_reponse.get("Titre", 'Titre non trouvé'),
        'url': url,
        'interessante': est_interessante,
        'resume': resume,
        'img': img
    }


async def main():
    announcements_data = get_announcements_data()
    await parse_announcements(announcements_data)  # Wait for parse_announcements to complete

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())  # Run the main function as an async event loop
