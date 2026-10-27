/* Offline sentence bank: shared by the browser and server. */
const SENTENCES =
/* SENTENCES_START */
[
  {
    "id": "chess-01",
    "topic": "chess",
    "text": "A patient chess player studies the whole board before moving a piece, because a quiet square can hide the beginning of a clever attack."
  },
  {
    "id": "chess-02",
    "topic": "chess",
    "text": "The knight jumped over a line of pawns and landed beside the king, turning a quiet afternoon match into a puzzle for both players."
  },
  {
    "id": "chess-03",
    "topic": "chess",
    "text": "Our chess club meets beside the school library every week, where new players learn that losing a game can teach more than winning one."
  },
  {
    "id": "chess-04",
    "topic": "chess",
    "text": "A rook travels in straight lines across the board, but finding its best square takes imagination, careful counting, and a little patience."
  },
  {
    "id": "chess-05",
    "topic": "chess",
    "text": "Two bishops watched the long diagonals while the queen waited near the center, ready to help defend the king from a sudden attack."
  },
  {
    "id": "chess-06",
    "topic": "chess",
    "text": "Before you capture an undefended pawn, check whether your opponent has left it there to lure your strongest piece away from the king."
  },
  {
    "id": "chess-07",
    "topic": "chess",
    "text": "The smallest pawn can become a queen by reaching the far side of the board, so even a single humble piece deserves a thoughtful plan."
  },
  {
    "id": "chess-08",
    "topic": "chess",
    "text": "A good chess puzzle asks you to notice what has changed, compare a few possible moves, and test your idea before touching a piece."
  },
  {
    "id": "chess-09",
    "topic": "chess",
    "text": "At the school tournament, every table had a chessboard, a clock, and two players who shook hands before beginning their first game."
  },
  {
    "id": "chess-10",
    "topic": "chess",
    "text": "When the king has no legal move and is not in check, the game ends in stalemate, giving both players a reason to study the final position."
  },
  {
    "id": "chess-11",
    "topic": "chess",
    "text": "The chess team packed wooden pieces into a small box after practice, then stayed a little longer to discuss the most surprising move."
  },
  {
    "id": "chess-12",
    "topic": "chess",
    "text": "Castling moves the king toward safety and brings a rook closer to the action, but first you must make sure that every rule is satisfied."
  },
  {
    "id": "chess-13",
    "topic": "chess",
    "text": "A fork attacks two pieces at once, forcing the other player to choose what to save while the knight waits proudly on its new square."
  },
  {
    "id": "chess-14",
    "topic": "chess",
    "text": "The queen is powerful, yet a coordinated group of smaller pieces can control the board and make her search for a safe place to rest."
  },
  {
    "id": "chess-15",
    "topic": "chess",
    "text": "An open file gave the rook a clear path into enemy territory, but a brave pawn blocked the entrance just before the final attack began."
  },
  {
    "id": "chess-16",
    "topic": "chess",
    "text": "Chess clocks encourage careful choices under pressure, reminding each player that a brilliant plan still needs enough time to carry it out."
  },
  {
    "id": "chess-17",
    "topic": "chess",
    "text": "The beginner wrote down each move in a notebook, hoping to replay the match later and discover where a promising attack had gone wrong."
  },
  {
    "id": "chess-18",
    "topic": "chess",
    "text": "Every square matters in a close endgame, when two kings and a handful of pawns turn the empty board into a delicate race for promotion."
  },
  {
    "id": "chess-19",
    "topic": "chess",
    "text": "The club arranged a friendly match for the fair, inviting visitors to solve a chess puzzle before trying a full game against a volunteer."
  },
  {
    "id": "chess-20",
    "topic": "chess",
    "text": "A strong defense begins with noticing all the threats against you, protecting loose pieces, and keeping calm when an unexpected move appears."
  },
  {
    "id": "computer-01",
    "topic": "computer",
    "text": "A computer follows instructions one step at a time, so a clear plan often saves more effort than typing a long program without thinking."
  },
  {
    "id": "computer-02",
    "topic": "computer",
    "text": "The robot followed a trail of blue squares across the classroom floor, stopping whenever its sensor noticed an obstacle in the next space."
  },
  {
    "id": "computer-03",
    "topic": "computer",
    "text": "A clear and useful variable name explains what a value means, helping the next programmer understand the code without guessing at its purpose."
  },
  {
    "id": "computer-04",
    "topic": "computer",
    "text": "Our first program printed a friendly greeting, then asked the visitor to choose a color for a tiny spaceship on the classroom screen."
  },
  {
    "id": "computer-05",
    "topic": "computer",
    "text": "A loop repeats a set of instructions until its job is done, allowing a short program to draw hundreds of stars across a dark background."
  },
  {
    "id": "computer-06",
    "topic": "computer",
    "text": "The class tested each part of the program separately, discovering a small mistake before it could become a much more confusing problem."
  },
  {
    "id": "computer-07",
    "topic": "computer",
    "text": "When a program gives a strange answer, trace the values carefully and look for the first step where the result differs from your plan."
  },
  {
    "id": "computer-08",
    "topic": "computer",
    "text": "A password should be hard to guess and kept private, just as the key to a locked cabinet belongs only to the person who needs access."
  },
  {
    "id": "computer-09",
    "topic": "computer",
    "text": "The students designed a maze on paper before writing code, marking the starting point and checking that every path led somewhere useful."
  },
  {
    "id": "computer-10",
    "topic": "computer",
    "text": "A binary number uses only zero and one, yet those simple digits can represent pictures, music, messages, and every letter on this page."
  },
  {
    "id": "computer-11",
    "topic": "computer",
    "text": "Good comments explain why a tricky choice was made, while clear code shows how the program carries out the steps that solve the problem."
  },
  {
    "id": "computer-12",
    "topic": "computer",
    "text": "The little game stored each score in a list, then sorted the results so the fastest players could find their names near the top of the screen."
  },
  {
    "id": "computer-13",
    "topic": "computer",
    "text": "Before deleting a file, check its name and location carefully, because a few seconds of attention can prevent an afternoon of extra work."
  },
  {
    "id": "computer-14",
    "topic": "computer",
    "text": "A function gives a useful task a name, letting a programmer reuse the same idea whenever another part of the program needs that result."
  },
  {
    "id": "computer-15",
    "topic": "computer",
    "text": "The animation moved a bright square across the screen, changing its position a little at a time to create the appearance of smooth motion."
  },
  {
    "id": "computer-16",
    "topic": "computer",
    "text": "Two curious students compared their solutions to the same puzzle and discovered that different algorithms can reach the very same correct answer."
  },
  {
    "id": "computer-17",
    "topic": "computer",
    "text": "A careful test includes ordinary examples and unusual cases, such as an empty list or a number that sits exactly on the allowed boundary."
  },
  {
    "id": "computer-18",
    "topic": "computer",
    "text": "The computer club built a simple weather display using sample data, then added labels so visitors could understand every number and symbol."
  },
  {
    "id": "computer-19",
    "topic": "computer",
    "text": "An algorithm is a sequence of clear steps for solving a problem, much like a recipe that explains how to turn ingredients into a finished meal."
  },
  {
    "id": "computer-20",
    "topic": "computer",
    "text": "The keyboard sent each letter to the program, which checked the input and displayed a helpful message whenever a required field was empty."
  },
  {
    "id": "carnival-01",
    "topic": "carnival",
    "text": "The carnival opened with bright flags above the gate, while volunteers arranged prizes and checked that every booth was ready for visitors."
  },
  {
    "id": "carnival-02",
    "topic": "carnival",
    "text": "A line of paper lanterns stretched between the tents, glowing softly as families gathered to enjoy the last games of the school fair."
  },
  {
    "id": "carnival-03",
    "topic": "carnival",
    "text": "The ring toss looked easy from across the yard, but landing a ring on the smallest bottle required a steady hand and a patient smile."
  },
  {
    "id": "carnival-04",
    "topic": "carnival",
    "text": "At the ticket booth, a volunteer counted colorful strips of paper while the next group planned which carnival games they wanted to try."
  },
  {
    "id": "carnival-05",
    "topic": "carnival",
    "text": "The prize wheel clicked past a row of painted stars before stopping on a tiny bell, sending a cheerful sound across the crowded schoolyard."
  },
  {
    "id": "carnival-06",
    "topic": "carnival",
    "text": "Our class painted a red and gold sign for the fair, adding large letters so visitors could read the name of the booth from far away."
  },
  {
    "id": "carnival-07",
    "topic": "carnival",
    "text": "A friendly dragon made from cardboard guarded the beanbag game, where players aimed for three round windows cut into its bright green belly."
  },
  {
    "id": "carnival-08",
    "topic": "carnival",
    "text": "The popcorn stand filled the air with a warm buttery smell as friends compared their tickets and searched for the next game on the map."
  },
  {
    "id": "carnival-09",
    "topic": "carnival",
    "text": "Behind the striped curtain, volunteers prepared a puppet show about a lost balloon that found its way home with help from a clever sparrow."
  },
  {
    "id": "carnival-10",
    "topic": "carnival",
    "text": "The tallest tent held a collection of handmade games, each designed by students who explained the rules and welcomed every curious visitor."
  },
  {
    "id": "carnival-11",
    "topic": "carnival",
    "text": "A basket of soft beanbags waited beside the target, and the volunteer reminded each player to stand behind the line before taking a turn."
  },
  {
    "id": "carnival-12",
    "topic": "carnival",
    "text": "The school band played a cheerful tune near the entrance while visitors followed colorful arrows toward the food tables and carnival games."
  },
  {
    "id": "carnival-13",
    "topic": "carnival",
    "text": "A sudden breeze lifted the corner of the booth banner, so two volunteers tied it firmly before welcoming the next group of eager players."
  },
  {
    "id": "carnival-14",
    "topic": "carnival",
    "text": "The guessing jar was filled with shiny wooden beads, inviting visitors to use a little mathematics before writing their estimates on a card."
  },
  {
    "id": "carnival-15",
    "topic": "carnival",
    "text": "At the end of the fair, every class helped collect paper cups and fold the tables, leaving the schoolyard as clean as it had been that morning."
  },
  {
    "id": "carnival-16",
    "topic": "carnival",
    "text": "A small train carried painted animal figures around a wooden track, passing a tiny station decorated with ribbons and bright paper flowers."
  },
  {
    "id": "carnival-17",
    "topic": "carnival",
    "text": "The face painting table offered stars, butterflies, and friendly robots, giving each visitor a chance to choose a colorful design of their own."
  },
  {
    "id": "carnival-18",
    "topic": "carnival",
    "text": "The duck pond game used floating wooden ducks with numbers underneath, and every careful catch earned a ticket toward a prize at the booth."
  },
  {
    "id": "carnival-19",
    "topic": "carnival",
    "text": "A robot played chess beside the carnival stage while visitors tried to predict its next move and students explained how its program worked."
  },
  {
    "id": "carnival-20",
    "topic": "carnival",
    "text": "The final bell rang across the fair as volunteers thanked the players, counted the remaining tickets, and packed the prizes away for next year."
  }
]
/* SENTENCES_END */
;
