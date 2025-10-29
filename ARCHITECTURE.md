# Explaining how the archtecture works.

The main queue is a minHeap in /flow/queue.py This is a single loop.

State Management is stored inside a database.
Fleet state overall and per ship
Market Prices
Waypoint Traits

Policy. When a ship is free, it asks for a job.
Use assignment planner to pick the highest profit per minute job.
Route planner. takes the job and finds a reasonable path.


# General notes.

The fog of war data will be stored in a database with an observed_at so we can have staleness.

We have a vehicle routing problem with the excavators and haulers.
I need to decide which strategy to use. Initial research suggests using a PDVRP(Pickup and Delivery Routing Problem) solution.
Refueling complicates this as we want ships to use optimal speeds.

Bandits vs Optimizers.
Run a known good route or explore a new route?

Policy/Guard rails
Max miners per waypoint. Ideally auto discover when we are being too inefficient. Unknown if this varies or not.
Price impact? How much do we personally affect prices? Can we anticpate this?

Junk dealing
Discovery profit margins and come up with a plan to discard junk not worth the time to sell.
