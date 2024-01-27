# SeLogerGPT Project

SeLogerGPT is a Python-based tool that automates the search and evaluation of real estate listings on the SeLoger website using OpenAI's GPT-4 and Scrapfly API. The tool filters listings according to predefined criteria and utilizes AI to determine the relevance of each property. If a property meets the criteria, the details are sent via Telegram for further review.

## Features

- Automated real estate listing search on SeLoger.com
- Advanced filtering by location, price, size, and other attributes
- Integration with OpenAI's GPT-4 for analyzing listing descriptions
- Telegram alerts for listings deemed interesting by GPT-4
- State management to avoid reprocessing the same listings

## Requirements

- Python 3.6+
- OpenAI API key
- Telegram Bot token and chat ID
- Scrapfly API key
- `python-telegram-bot` library
- `scrapfly` library
- `openai` library
- `parsel` library
- `dotenv` library

## Configuration

Before running the script, you must set up the following environment variables in a `.env` file at the project's root:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
OPENAI_API_KEY=your_openai_api_key
SCRAPFLY_API_KEY=your_scrapfly_api_key
```

Additionally, populate the `search_config.py` file with your search parameters and criteria template. Example template provided below as `search_config.py.template`.

## Usage

1. Clone the repository:
   ```
   git clone https://github.com/your-repo/SeLogerGPT.git
   ```
2. Navigate to the project directory:
   ```
   cd SeLogerGPT
   ```
3. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```
4. Configure your `.env` file with the necessary API keys and tokens.
5. Update `search_config.py` with your search parameters.
6. Run the script:
   ```
   python SeLogerGPT.py
   ```
7. Check your Telegram for alerts regarding new interesting listings.

## Files and Directories

- `SeLogerGPT.py`: Main script to run the search and process listings.
- `.env`: Configuration file for storing sensitive API keys and tokens.
- `search_config.py`: Configuration file for specifying search parameters and criteria.
- `search_config.py.template`: Template for creating your own `search_config.py`.
- `requirements.txt`: List of Python libraries required for running the script.
- `img/`: Directory to store downloaded images from listings.
- `processed_urls.json`: State file to store already processed listing URLs.
- `announcement_results.json`: State file to store listing details.

## Disclaimer

Use this script responsibly and in accordance with the terms of service of SeLoger.com, Telegram, OpenAI, and Scrapfly. This project is for educational purposes and is not affiliated with SeLoger or any of the API providers.