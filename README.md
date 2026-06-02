# veterinarian_19

Odoo 19 veterinary clinic demo and related addons.

## Modules

| Module | Description |
|--------|-------------|
| `base_industry_data` | Industry demo base data |
| `veterinary_clinic` | Veterinary clinic SaaS app (Studio pets, appointments, POS) |
| `veterinary_petget_bridge` | Links clinic pets with Petget dog knowledge |
| `petget_core` | Petget foundation (documents, reminders, notes) |
| `petget_dog` | Dog breeds and animal fields |
| `petget_dog_knowledge` | Breed knowledge, life stages, growth |
| `pet_management` | Pet management addon |
| `planning_field_service_worksheet` | FSM worksheets for home visits |
| `pos_stock` | POS stock helpers |

## Source

Synced from `edafa__veterinary_demo` (local demo workspace).

## Branches

- `app-veterinary_clinic` — original veterinary clinic app
- `feature/edafa-veterinary-demo` — full demo stack including Petget bridge and pet management

## Odoo addons path

Add this repository root to your `addons_path`, then install `veterinary_clinic` and `veterinary_petget_bridge` (and dependencies as needed).
