# Fleet Management Module -- System Requirements Specification (SRS)

## Integration with Django Implementation Tracker

Version: 1.0\
Date: 2026-02-18

------------------------------------------------------------------------

# 1. Background

The Implementation Tracker system currently manages program activities.
This module extends the system to include Fleet Management
functionality, allowing users to request transport for:

1.  Existing implementation activities
2.  New ad-hoc activities

The system will introduce new user roles and workflows to support
structured vehicle allocation and tracking.

------------------------------------------------------------------------

# 2. Objectives

-   Enable transport requests linked to tracker activities
-   Allow transport requests for standalone (ad-hoc) activities
-   Introduce new user roles: Driver and Transport Officer
-   Provide structured approval and booking workflow
-   Prevent double-booking of vehicles and drivers
-   Enable reporting and dashboard visibility

------------------------------------------------------------------------

# 3. User Roles & Permissions

## 3.1 Standard User (Activity Owner)

Permissions: - Create transport request - View own requests - Edit
request before approval - Cancel request before allocation - View
assigned vehicle and driver

------------------------------------------------------------------------

## 3.2 Transport Officer

Permissions: - View all transport requests - Approve or reject
requests - Assign vehicle and driver - Modify allocations - Mark trip as
completed - Mark trip as cancelled - View fleet availability calendar -
Access fleet dashboard - Manage vehicle master data - Manage driver
master data

------------------------------------------------------------------------

## 3.3 Driver

Permissions: - View assigned trips - Confirm trip acceptance - Update
trip status (En route, Started, Completed) - Record start mileage -
Record end mileage - Add trip notes/incidents

Restrictions: - Cannot approve requests - Cannot modify assignments -
Cannot view other drivers' schedules

------------------------------------------------------------------------

# 4. Functional Requirements

## 4.1 Transport Request Creation

### 4.1.1 Linked to Existing Activity

-   Select existing implementation activity
-   Auto-populate activity name, location, dates
-   Editable pickup location
-   Editable destination
-   Departure datetime
-   Return datetime
-   Number of passengers
-   Justification
-   Special requirements

### 4.1.2 Ad-Hoc Request

-   Activity name
-   Description
-   Location
-   Departure and return datetime
-   Justification

System must generate: - Unique Request ID - Status = Pending Approval

------------------------------------------------------------------------

## 4.2 Workflow Statuses

1.  Draft
2.  Pending Approval
3.  Approved
4.  Rejected
5.  Allocated
6.  In Progress
7.  Completed
8.  Cancelled

Rules: - Only Transport Officer can approve/reject - Allocation requires
vehicle + driver - Cannot allocate if conflicts exist - Driver moves
status to In Progress - Completion requires end mileage

------------------------------------------------------------------------

## 4.3 Vehicle Master Data

Fields: - Registration number (unique) - Make/model - Type - Fuel type -
Status (Available, Booked, Maintenance, Out of Service) - Assigned
location - Last service date - Next service due

Constraints: - No overlapping bookings - Cannot assign if not Available

------------------------------------------------------------------------

## 4.4 Driver Master Data

Fields: - Full name - License number - Phone number - License expiry
date - Status (Available, Assigned, On Leave) - Assigned location

Constraints: - No overlapping assignments

------------------------------------------------------------------------

## 4.5 Allocation Logic

System must: - Validate vehicle availability - Validate driver
availability - Prevent datetime overlaps - Lock allocation upon
confirmation

------------------------------------------------------------------------

## 4.6 Trip Logging

Driver must enter: - Start mileage - End mileage - Incident notes
(optional)

System auto-calculates: - Distance traveled

------------------------------------------------------------------------

## 4.7 Dashboard Requirements

Must display: - Total vehicles - Available vehicles - Pending
approvals - Active trips - Monthly completed trips - Vehicle utilization
rate - Driver utilization rate - Distance per vehicle - Maintenance
alerts

------------------------------------------------------------------------

# 5. Non-Functional Requirements

## Performance

-   Allocation validation under 2 seconds
-   Dashboard load under 3 seconds

## Security

-   Role-Based Access Control (RBAC)
-   Audit logging for approvals and allocations
-   Immutable request history

## Data Integrity

-   Unique vehicle registration
-   Unique request ID
-   Required datetime validation
-   Conflict detection logic

## Scalability

-   Support \>100 vehicles
-   Support \>300 users

------------------------------------------------------------------------

# 6. Core Database Models

-   Vehicle
-   Driver
-   TransportRequest
-   TripAllocation
-   TripLog
-   MaintenanceRecord

Relationships: - TransportRequest → Linked Activity (optional FK) -
TransportRequest → RequestedBy (User FK) - TripAllocation → Vehicle
(FK) - TripAllocation → Driver (FK)

------------------------------------------------------------------------

# 7. Audit Trail

System must record: - Approval timestamp - Allocating officer -
Allocation modifications - Driver confirmation timestamps

------------------------------------------------------------------------

# 8. Future Enhancements

-   Fuel tracking
-   Maintenance automation
-   SMS notifications
-   GPS integration
-   Driver mobile interface

------------------------------------------------------------------------

# Conclusion

This module transforms the Implementation Tracker into an integrated
Activity + Transport Management System ensuring accountability, resource
optimization, structured workflow, and operational visibility.
