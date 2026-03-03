About Dataset by ilyazored
team_won: The name of the team that won the match. For example, values may include paiN, ALTERNATE aTTaX, etc.

team_lost: The name of the team that lost the match. For example, values may include RED Canids, Case, etc.

stars_of_tournament: The level of importance of the tournament, expressed in stars or another rating format. The higher the value, the more prestigious the tournament. Typically, values range from 0 to 5.

shape: The format of the match, such as bo3 or bo5, indicating the number of games required to win. For example, bo3 means "best of 3," meaning the winner is the one who wins two out of three matches.

event_name: The name of the tournament or event, for example, ESL Challenger League Season 48 South America. This indicates the tournament in which the teams participated.

score: The final score of the match, for example, 2 - 0 or 1 - 2. The first element indicates the number of maps won by the first team, and the second indicates the number won by the second team.

time: The date the match took place in the format YYYY-MM-DD, for example, 2024-10-24. This indicates the exact time when the match was played, which is important for analysis and predicting future matches.

team1: The name of the first team in the match. This is important for identifying specific matches and analyzing their outcomes.

team2: The name of the second team in the match. Similar to team1, this is used for identifying matches.

target: The label indicating the match result, for example, 1 if team1 won or 0 if team1 lost.

```py
import kagglehub

# Download latest version
path = kagglehub.dataset_download("ilyazored/hltv-match-resultscs2")

print("Path to dataset files:", path)
```