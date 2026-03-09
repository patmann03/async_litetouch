Litetouch Integration library for interfacing with Savant SSL-P018 / 5000LC Controllers 

Sample Config

light:
  - platform: litetouch
    host: 10.3.1.35
    port: 10001

    # 4 concurrent command sockets (as requested)
    command_connections: 8

    # Keep notifications isolated on a separate socket (recommended)
    event_connection: true

    # default fade time (seconds) for DSMLV transitions
    transition: 2

    # Your lights
    lights:
    # Basement
    ## Basement
    - name: Hall Sconce Basement 1
      module: "0022"
      output: 4
      location: "Basement"
      floor: "Basement"
      ltcode: "LB50"
    - name: Pool Table Sconces Basement 1
      module: "0022"
      output: 2
      location: "Basement"
      floor: "Basement"
      ltcode: "LB46"
    - name: Pool Table Sconces Basement 2
      module: "0022"
      output: 1
      location: "Basement"
      floor: "Basement"
      ltcode: "LB39"
    - name: Pool Table Chandelier
      loadid: 269
      module: "0001"
      output: 0
      location: "Basement"
      floor: "Basement"
      ltcode: "LB07"
