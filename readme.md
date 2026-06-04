Table of Contents

- [Introduction](#introduction)
  - [Tech Stack and design philosophy](#tech-stack-and-design-philosophy)
    - [Project Structure](#project-structure)
      - [Backend](#backend)
    - [Action Flow](#action-flow)
  - [State of the Project](#state-of-the-project)
      - [Implemented Features:](#implemented-features)
      - [Not yet implemented:](#not-yet-implemented)
    - [Frontend](#frontend)
      - [MAP](#map)
      - [Action Prompter](#action-prompter)
      - [Cards In Hand](#cards-in-hand)
      - [Top Row](#top-row)
      - [Player Boards](#player-boards)
- [Running Locally/Development](#running-locallydevelopment)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Run Locally with Docker](#run-locally-with-docker)

# Introduction

This is a web-based adaptation of the board game Root by Cole Wehrle. Root is a complex board game with many different factions, each with their own unique rules and mechanics.

The eventual aim is to implement all current factions and one day, maybe fan-made factions as well.

A demo version of the game can be played at [https://root.mattdf.net/](https://root.mattdf.net/). Click a Demo User button to sign in and play around with any "ongoing" games, or go to the "create game" tab and click the Create Demo Game to quickly start a game with 4 factions. Within a game, use the faction control below the board to switch between users. The player info on the left of the screen can be clicked to bring up the player boards. The demo is not designed for mobile in mind. The demo usually runs smoothly, but it is on a cheap VM and sometimes the server might not have much compute which will make the demo crawl.

## Tech Stack and design philosophy

This project is built using Python and Django. The frontend is built using React and Tanstack Query for interaction with the API. The openAPI schema is generated with drf-spectacular, which allows for easier development between the front- and back-end

Real time updates are handled using django-channels and Redis.

The project is designed such that the server handles all game logic and the frontend handles all user interaction. The frontend will not be responsible for any game logic, as that would mean duplicating the logic in the frontend and backend in different languages, which is hard to maintain and likely to lead to bugs and inconsistencies.

The API can be split into two categories of responsibilities. The first is providing gamestate information. The second category is handling player actions and is largely RPC-style, with endpoints for each player action. As the game objects are all intertwined, operating on individual "resources" is not practical within a single game.

### Project Structure

#### Backend

<ul>
<li> <b>Persistence Layer:</b> The database will hold all state for the game, which is defined in the models module.</li>
<li> <b>Selector Layer:</b> The queries module holds logic that queries the database, but does not modify it.</li>
<li><b>Service Layer:</b>The transactions module holds logic that modifies the database, checking for game state using queries.</li>
<li> <b>API Layer:</b> Views provide gamestate information and post methods to submit moves. These moves are validated (with queries) and then executed using transactions.</li>
</ul>

### Action Flow

The action flow relies on a metadata-driven client-server interaction. The server provides the client with details of data to send and where to send it, and the client uses this information to drive the UI and make requests. This means that the client never needs to know about the game logic, and the server never needs to know about the UI.

Here is a detailed look at the process:

<ul>
<li>The client requests the endpoint corresponding to the current action step, which may be a step of a player's turn, or resolving their part of an event like battle.</li>
<li>The client then makes a request of the provided endpoint, and receives a response detailing the instructions for the current action step, the data the client should send, and the endpoint to send it to.</li>

<li>
When the user interacts with the UI, the client packages the user's input into the data format provided by the server and sends it to the provided endpoint. If it is a multistep process, the server will validate the first step and send back the next one, or provide the error if the first step is invalid. This continues until the server sends back a "completed" step.
</li>
<li>
If the server sends back a "completed" step, the client will know that the action is complete (gamestate data is refetched and displayed). If not, the client receives a response corresponding to the next action step, and the cycle repeats until the action is completed.
</li>
<li>
Validation of timing and the player making requests is handled by the custom GameActionView base class. Anything corresponding to a player action is subclassed from this clas and validation can be customized as needed.
</li>
</ul>

## State of the Project

Games can be created and played with 6 fully implemented factions. All basic game features are implemented and the core functions have been well tested. More factions will be added, more features will be provided, and the UI will be improved over time.

#### Implemented Features:

- Basic Setup Rules
- 6 factions have been fully implemented: Cats, Birds, Woodland Alliance, Crows, Underground Duchy (Moles), and Riverfolk Company (Rats).
- Cards can be crafted.
  - Cards with passive effects are checked for and handled in the appropriate business logic.
  - Cards with active effects also work, launching events if the action has a narrow timing window or are simply made available when usable if they have a broader timing window.
- Game end conditions have been added.
- Game Browser to create, join, switch between, and delete games.
- Undo functionality
- Dominance Conditions/Dominance Swapping
- Game Logs
- Cards revealed during play are displayed in a widget
- Discard Piles are displayed in a widget
- Items available to craft are displayed in a widget

#### Not yet implemented:

- Advanced Setup Rules (need to have enough factions implemented for this to be worthwhile)

### Frontend

The frontend is minimal, but will be augmented over time. Components such as cards and clearings are clickable and can be used to submit actions to the server.

#### MAP

Clearings are clickable for actions that require a clearing to be selected.

![Screenshot of the frontend](images/map.png)

#### Action Prompter

Displays the current action step and the faction that needs to take an action. If options have been provided, they will be displayed as buttons that submit to the server.

![Screenshot of the frontend](images/prompter.png)

#### Cards In Hand

Mousing over the hand of cards will expand them, and the hovered card will be brought to the front. Clicking a card will submit it to the server if relevant.

![Screenshot of the frontend](images/cards.png)

#### Top Row

The top row provides game information, app navigation, and access to player board and other game information modals, such as the discard pile, items available to craft, and the discard pile.
![Screenshot of the frontend](images/toprow.png)

#### Player Boards

Player boards provide information on that player's turn structure, special abilities, and any other details for that faction. Information that only the player of the faction can see is hidden from other players.
When a piece on a track covers information, that info is displayed in a tooltip. Extra information is displayed in tooltips when hovering over the board to conserve space
![Cats Player Board](images/cat_board.png)
![Birds Player Board](images/bird_board.png)
Decree actions have a checkbox to indicate if the decree is used.
![Woodland Alliance Player Board](images/wa_board.png)

![Crows Player Board](images/crow_board.png)


![Moles Player Board](images/moles_board.png)

![Rats Player Board](images/rats_board.png)

# Running Locally/Development

## Prerequisites

- Python 3.10+
- Node.js
- Docker(optional)

## Setup

The database is setup to run locally using sqlite3. You will need to run the initial migrations to set the database up before running the server the first time:

```
python manage.py makemigrations
python manage.py migrate
```

Now add the user accounts that the demo expects
```
python manage.py shell
>>> from django.contrib.auth.models import User
>>> user=User.objects.create_user('user1', password='password')
>>> user=User.objects.create_user('user2', password='password')
>>> user=User.objects.create_user('user3', password='password')
>>> user=User.objects.create_user('user4', password='password')
>>> user.save()
>>> quit()
```

To run the project locally for development, I use npm and vite to serve the frontend and django to run the backend. the packages for the frontend are listed in the package.json file and the packages for the backend are listed in the requirements.txt file. To run the backend, you will need to be in the project root and run:

`python manage.py runserver`

To run the frontend, you will need to be in the folder ./frontend and run:

`npm run dev`

If all goes well, the frontend will be available at http://localhost:5173.

In addition, Redis is used for the websocket connection to handle live updates. This isn't strictly needed for development but it may be a bit sluggish without it. The docker-compose.yml file is set up to run Redis locally in Docker and the app will be set up to use it automatically. If you have docker, at the root of this project folder run:

`docker-compose up -d redis`

to start the redis service.

## Run Locally with Docker

The server can be run locally in Docker instead from an image, which has the advantage that you don't need to set up or install Python or Node.js. The disadvantage is that any changes will require a rebuild of the image, which is cumbersome for development. 

The Docker image is not currently publicly available, but can be built using the dockerfile in the project root. Simply navigate to project root and call `docker-compose build web` to build the image, and when that is complete, run `docker-compose up -d web redis` to run the services. In this configuration, the project is served at http://localhost:8000. The first time this is run, the local database will still need to be migrated/created, which can be done inside docker with `docker-compose run --rm python manage.py migrate`.